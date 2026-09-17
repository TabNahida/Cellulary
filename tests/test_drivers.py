import pytest
from test_modem import FakeTransport

from cellulary import ATCommandError, Modem, UnsupportedModemError
from cellulary.drivers import (
    EC25Driver,
    EC200ADriver,
    EC801EDriver,
    ModemDriver,
    registered_drivers,
    select_driver,
)


@pytest.mark.parametrize("manufacturer,model,driver", [
    ("Quectel", "EC200A", EC200ADriver),
    ("Quectel", "EC200A-EU", EC200ADriver),
    ("Quectel", "EC801E", EC801EDriver),
    ("Quectel", "EC801E-CN", EC801EDriver),
    ("Quectel", "EC25", EC25Driver),
    ("Quectel", "EC25-E", EC25Driver),
    ("Other", "EC801E", ModemDriver),
    ("NotQuectel", "EC200A", ModemDriver),
    ("Quectel", "EC200ABOGUS", ModemDriver),
    ("Quectel", "EC801", ModemDriver),
])
def test_registry_selects_exact_vendor_and_model_families(manufacturer, model, driver):
    selected = select_driver({"manufacturer": manufacturer, "model": model}, lambda *_a, **_k: None)
    assert type(selected) is driver


def test_each_model_has_a_separate_registered_implementation():
    assert {driver.profile.name for driver in registered_drivers()} == {"quectel-ec200a", "quectel-ec801e", "quectel-ec25"}
    assert EC200ADriver.__module__ != EC801EDriver.__module__ != EC25Driver.__module__


def test_ec801_firmware_without_sms_advertises_the_real_limitation():
    transport = FakeTransport({"AT+CMGF=?": ATCommandError("AT+CMGF=?", "ERROR")})
    modem = Modem("FAKE", transport=transport)
    identity = modem.identify()
    assert identity["sms_support"] == "unsupported"
    assert identity["sms_reason_code"] == "sms_firmware_unsupported"
    assert "sms" not in identity["capabilities"]
    with pytest.raises(UnsupportedModemError):
        modem.send_sms("123", "hello")
    assert "AT+CMGF=0" not in transport.commands
    assert transport.payloads == []


def test_ec801_future_firmware_can_enable_sms_only_after_pdu_capability_response():
    transport = FakeTransport({"AT+CMGF=?": ["+CMGF: (0-1)"]})
    modem = Modem("FAKE", transport=transport)
    assert modem.identify()["sms_support"] == "supported"
    assert modem.send_sms("123", "hello")["status"] == "submitted"


@pytest.mark.parametrize("method,arguments", [("dial", ("123",)), ("answer", ()), ("hangup", ()), ("list_calls", ())])
def test_ec801_rejects_voice_before_any_call_commands(method, arguments):
    transport = FakeTransport()
    modem = Modem("FAKE", transport=transport)
    with pytest.raises(UnsupportedModemError):
        getattr(modem, method)(*arguments)
    assert not any(command.startswith(("ATD", "ATA", "ATH", "AT+CHUP", "AT+CLCC")) for command in transport.commands)


def test_ec200a_voice_hangup_uses_documented_voice_command():
    transport = FakeTransport({"AT+CGMM": ["EC200A"]})
    Modem("FAKE", transport=transport).hangup()
    assert transport.commands[-1] == "AT+CHUP"


def test_cached_identity_cannot_be_mutated_by_a_caller():
    modem = Modem("FAKE", transport=FakeTransport())
    identity = modem.identify()
    identity["capabilities"].clear()
    assert modem.identify()["capabilities"]
