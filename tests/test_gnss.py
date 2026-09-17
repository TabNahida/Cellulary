import pytest
from test_modem import FakeTransport

from cellulary import ATCommandError, Modem, UnsupportedModemError
from cellulary.drivers.quectel.ec25 import parse_qgpsloc


def ec25(replies=None):
    transport = FakeTransport({"AT+CGMM": ["EC25-E"], "AT+CGMR": ["EC25_TEST_ONLY"], **(replies or {})})
    return Modem("FAKE", transport=transport), transport


def test_valid_decimal_location_is_parsed_with_utc_and_measurements():
    line = "+QGPSLOC: 123456.250,51.5074,-0.1278,0.8,25.5,3,180.0,12.0,6.48,170926,12"
    modem, transport = ec25({"AT+QGPS?": ["+QGPS: 1"], "AT+QGPSLOC=2": [line]})
    result = modem.gnss_location()
    assert result["supported"] is True
    assert result["enabled"] is True
    assert result["fix"] is True
    assert result["latitude"] == 51.5074
    assert result["longitude"] == -0.1278
    assert result["timestamp"] == "2026-09-17T12:34:56.250000+00:00"
    assert result["altitude_m"] == 25.5
    assert result["satellites"] == 12
    assert result["verification"] == "protocol_tests_only"
    assert "AT+QGPS=1" not in transport.commands


def test_no_fix_is_a_normal_read_result():
    modem, _ = ec25({"AT+QGPS?": ["+QGPS: 1"], "AT+QGPSLOC=2": ATCommandError("AT+QGPSLOC=2", "+CME ERROR: 516")})
    result = modem.gnss_location()
    assert result["supported"]
    assert result["enabled"]
    assert not result["fix"]
    assert result["reason_code"] == "gnss_no_fix"
    assert "latitude" not in result


def test_status_does_not_read_precise_location():
    modem, transport = ec25({"AT+QGPS?": ["+QGPS: 1"]})
    assert modem.gnss_status()["enabled"] is True
    assert "AT+QGPSLOC=2" not in transport.commands


def test_disabled_receiver_is_not_started_or_queried_for_a_fix():
    modem, transport = ec25({"AT+QGPS?": ["+QGPS: 0"]})
    result = modem.gnss_location()
    assert result["reason_code"] == "gnss_disabled"
    assert "AT+QGPSLOC=2" not in transport.commands
    assert "AT+QGPS=1" not in transport.commands


@pytest.mark.parametrize("method,initial,command", [("start_gnss", 0, "AT+QGPS=1"), ("stop_gnss", 1, "AT+QGPSEND")])
def test_gnss_controls_verify_firmware_before_writing(method, initial, command):
    modem, transport = ec25({"AT+QGPS?": [f"+QGPS: {initial}"]})
    result = getattr(modem, method)()
    assert transport.commands[-2:] == ["AT+QGPS?", command]
    assert result["requested"]
    assert not result["fix"]


def test_capability_test_can_enable_ec25_when_read_form_is_unavailable():
    modem, transport = ec25({"AT+QGPS?": ATCommandError("AT+QGPS?", "ERROR"), "AT+QGPS=?": ["+QGPS: (1-3),(1-255),(0-1000),(0-1000)"]})
    assert modem.start_gnss()["requested"]
    assert transport.commands[-3:] == ["AT+QGPS?", "AT+QGPS=?", "AT+QGPS=1"]


@pytest.mark.parametrize("model,revision", [("EC801E", "EC801ECNCGR07A03M02"), ("EC200A", "EC200AEUV1HAR02A08M16"), ("EC200A-CN", "CN_TEST"), ("Other", "UNKNOWN")])
def test_unsupported_models_never_receive_gnss_probe_or_control_commands(model, revision):
    transport = FakeTransport({"AT+CGMM": [model], "AT+CGMR": [revision]})
    modem = Modem("FAKE", transport=transport)
    assert modem.gnss_status()["supported"] is False
    with pytest.raises(UnsupportedModemError):
        modem.start_gnss()
    with pytest.raises(UnsupportedModemError):
        modem.stop_gnss()
    assert not any("QGPS" in command for command in transport.commands)


def test_ec25_without_firmware_support_rejects_before_writes():
    modem, transport = ec25({"AT+QGPS?": ATCommandError("AT+QGPS?", "ERROR"), "AT+QGPS=?": ATCommandError("AT+QGPS=?", "ERROR")})
    with pytest.raises(UnsupportedModemError):
        modem.start_gnss()
    assert "AT+QGPS=1" not in transport.commands


@pytest.mark.parametrize("latitude,longitude", [("5130.444", "-0.1278"), ("nan", "0"), ("0", "inf"), ("0", "181")])
def test_malformed_coordinates_never_become_a_fix(latitude, longitude):
    with pytest.raises(ValueError):
        parse_qgpsloc(f"+QGPSLOC: 123456.0,{latitude},{longitude},0.8,25.5,3,0,0,0,170926,12")


def test_zero_coordinates_are_a_valid_geographic_fix():
    result = parse_qgpsloc("+QGPSLOC: 123456.0,0,0,0.8,0,3,0,0,0,170926,12")
    assert result["fix"]
    assert result["latitude"] == 0
    assert result["longitude"] == 0
