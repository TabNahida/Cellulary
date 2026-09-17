import pytest

from cellulary import ATCommandError, ATResponse, Modem, SMSDeliveryError, UnsupportedModemError, encode_sms


class FakeTransport:
    def __init__(self, replies=None):
        self.replies = {"AT+CGMI": ["Quectel"], "AT+CGMM": ["EC801E"], "AT+CGMR": ["EC801ECNCGR07A03M02"], "AT+CGSN": ["123456789012345"], "AT+CMGF=?": ["+CMGF: (0,1)"]}
        self.replies.update(replies or {})
        self.commands = []
        self.payloads = []

    def command(self, command, **kwargs):
        self.commands.append(command)
        reply = self.replies.get(command, [])
        if isinstance(reply, Exception):
            raise reply
        return ATResponse(command, reply)

    def prompt_command(self, command, payload, **kwargs):
        self.commands.append(command)
        self.payloads.append(payload)
        if len(self.payloads) == 2 and "fail_second_segment" in self.replies:
            raise ATCommandError(command, "+CMS ERROR: 500")
        return ATResponse(command, [f"+CMGS: {len(self.payloads)}"])

    def open(self):
        return self

    def close(self):
        pass


def test_identification_is_cached_and_unknown_manufacturer_not_supported():
    transport = FakeTransport()
    modem = Modem("FAKE", transport=transport)
    assert modem.identify()["profile"] == "quectel-ec801e"
    modem.identify()
    assert transport.commands.count("AT+CGMM") == 1
    unknown = Modem("FAKE", transport=FakeTransport({"AT+CGMI": ["Other"]}))
    with pytest.raises(UnsupportedModemError):
        unknown.send_sms("123", "test")


@pytest.mark.parametrize("error", ["+CME ERROR: 10", "+CME ERROR: SIM not inserted"])
def test_absent_sim_is_a_normal_status(error):
    transport = FakeTransport({"AT+CPIN?": ATCommandError("AT+CPIN?", error), "AT+CSQ": ["+CSQ: 99,99"], "AT+CEREG?": ["+CEREG: 0,0"], "AT+COPS?": ["+COPS: 0,,"]})
    status = Modem("FAKE", transport=transport).status()
    assert status["sim"]["state"] == "absent"
    assert status["signal"]["dbm"] is None
    assert status["registration"]["registered"] is False
    assert status["operator"]["name"] == ""


def test_roaming_registration_and_multiple_pdp_contexts():
    transport = FakeTransport({"AT+CPIN?": ["+CPIN: READY"], "AT+CSQ": ["+CSQ: 23,99"], "AT+CEREG?": ["+CEREG: 0,5"], "AT+COPS?": ['+COPS: 0,2,"23430",7'], "AT+CGATT?": ["+CGATT: 1"], "AT+CGACT?": ["+CGACT: 1,1", "+CGACT: 8,1"], "AT+CGDCONT?": ['+CGDCONT: 1,"IP","internet","10.2.3.4",0,0']})
    status = Modem("FAKE", transport=transport).status()
    assert status["registration"]["roaming"]
    assert status["signal"]["dbm"] == -67
    assert status["data"]["attached"]
    assert status["data"]["contexts"] == [{"context_id": 1, "active": True, "pdp_type": "IP", "apn": "internet", "configured_address": "10.2.3.4", "address": None, "addresses": []}, {"context_id": 8, "active": True, "address": None, "addresses": []}]
    assert status["data"]["host_network_managed"] is False


def test_sms_list_decodes_pdu_and_retains_storage_index():
    pdu = encode_sms("12345", "中文")[0]["pdu"]
    transport = FakeTransport({"AT+CMGL=4": ["+CMGL: 2,1,,18", pdu]})
    sms, = Modem("FAKE", transport=transport).list_sms()
    assert sms["index"] == 2
    assert sms["text"] == "中文"


def test_multipart_submission_reports_each_reference():
    transport = FakeTransport()
    result = Modem("FAKE", transport=transport).send_sms("+12345", "中" * 71)
    assert result["segments"] == 2
    assert result["references"] == [1, 2]
    assert result["status"] == "submitted"


def test_partial_multipart_failure_exposes_already_submitted_references():
    transport = FakeTransport({"fail_second_segment": True})
    with pytest.raises(SMSDeliveryError) as caught:
        Modem("FAKE", transport=transport).send_sms("123", "中" * 71)
    assert caught.value.references == [1]
    assert caught.value.total_segments == 2
    assert "Do not retry automatically" in str(caught.value)


def test_apn_and_dial_validation_happens_before_io():
    transport = FakeTransport()
    modem = Modem("FAKE", transport=transport)
    with pytest.raises(ValueError):
        modem.configure_apn('internet"\rATD999;')
    with pytest.raises(ValueError):
        modem.dial("123;AT")
    with pytest.raises(ValueError):
        modem.activate_data(True)
    assert transport.commands == []


def test_voice_call_listing():
    transport = FakeTransport({"AT+CGMM": ["EC200A"], "AT+CLCC": ['+CLCC: 1,1,4,0,0,"+4412345",145']})
    calls = Modem("FAKE", transport=transport).list_calls()
    assert calls == [{"index": 1, "direction": "incoming", "state": 4, "mode": 0, "multiparty": False, "number": "+4412345"}]


def test_explicit_sms_notifications_request_storage_indications():
    transport = FakeTransport()
    result = Modem("FAKE", transport=transport).enable_sms_notifications()
    assert result["notification"] == "+CMTI"
    assert transport.commands[-1] == "AT+CNMI=2,1,0,0,0"


def test_pdp_address_comes_from_assigned_addresses_not_configured_address():
    transport = FakeTransport({"AT+CGDCONT?": ['+CGDCONT: 1,"IPV4V6","internet","0.0.0.0",0,0'], "AT+CGPADDR": ['+CGPADDR: 1,"10.4.5.6","2001:db8::1"', '+CGPADDR: 8,"0.0.0.0"']})
    contexts = Modem("FAKE", transport=transport).data_status()["contexts"]
    assert contexts[0]["configured_address"] == "0.0.0.0"
    assert contexts[0]["address"] == "10.4.5.6"
    assert contexts[0]["addresses"] == ["10.4.5.6", "2001:db8::1"]
    assert contexts[1]["address"] is None


def test_pdp_address_query_failure_does_not_present_configured_ip_as_assigned():
    transport = FakeTransport({"AT+CGDCONT?": ['+CGDCONT: 1,"IP","internet","192.0.2.2",0,0'], "AT+CGPADDR": ATCommandError("AT+CGPADDR", "ERROR")})
    data = Modem("FAKE", transport=transport).data_status()
    assert data["contexts"][0]["address"] is None
    assert data["errors"] == [{"command": "AT+CGPADDR", "error": "ERROR"}]


@pytest.mark.parametrize("state,connected", [(0, False), (1, True), (2, None)])
def test_usb_status_preserves_query_fields_and_does_not_claim_host_connectivity(state, connected):
    line = f"+QNETDEVCTL: 3,1,1,{state}"
    transport = FakeTransport({"AT+QNETDEVCTL?": [line]})
    result = Modem("FAKE", transport=transport).usb_data_status()
    assert result["supported"]
    assert result["operation"] == 3
    assert result["cid"] == 1
    assert result["urc"] == 1
    assert result["state"] == state
    assert result["connected"] is connected
    assert result["raw"] == [line]
    assert result["scope"] == "usb_modem"
    assert result["host_network_managed"] is False
    assert "AT+QNETDEVCTL=?" not in transport.commands


@pytest.mark.parametrize("connect,expected", [(True, "AT+QNETDEVCTL=1,1,1"), (False, "AT+QNETDEVCTL=0,1,0")])
def test_usb_data_mutation_uses_documented_sequence_after_verification(connect, expected):
    transport = FakeTransport({"AT+QNETDEVCTL?": ["+QNETDEVCTL: 0,0,0,0"]})
    modem = Modem("FAKE", transport=transport)
    result = modem.connect_usb_data() if connect else modem.disconnect_usb_data()
    assert transport.commands[-2:] == ["AT+QNETDEVCTL?", expected]
    assert not any(command.startswith(("AT+CGDCONT=", "AT+QCFG=", "AT+CFUN=", "AT+CGACT=")) for command in transport.commands)
    assert result["requested"] is True
    assert result["status"] == ("connect_requested" if connect else "disconnect_requested")
    assert result["connected"] is None
    assert result["host_network_managed"] is False


def test_usb_capability_test_can_verify_firmware_without_read_form():
    transport = FakeTransport({"AT+QNETDEVCTL?": ATCommandError("AT+QNETDEVCTL?", "ERROR"), "AT+QNETDEVCTL=?": ["+QNETDEVCTL: (0,1,3),(1-15),(0-1)"]})
    modem = Modem("FAKE", transport=transport)
    state = modem.usb_data_status()
    assert state["supported"]
    assert state["connected"] is None
    assert state["capabilities"]["context_ids"] == list(range(1, 16))
    assert state["evidence"] == "test"
    modem.connect_usb_data(15)
    assert transport.commands[-3:] == ["AT+QNETDEVCTL?", "AT+QNETDEVCTL=?", "AT+QNETDEVCTL=1,15,1"]


@pytest.mark.parametrize("replies", [
    {"AT+QNETDEVCTL?": ATCommandError("AT+QNETDEVCTL?", "ERROR"), "AT+QNETDEVCTL=?": ATCommandError("AT+QNETDEVCTL=?", "ERROR")},
    {"AT+QNETDEVCTL?": [], "AT+QNETDEVCTL=?": []},
    {"AT+QNETDEVCTL?": ["+QNETDEVCTL: malformed"], "AT+QNETDEVCTL=?": ["+QNETDEVCTL: (0,1),(1-99999),(0-1)"]},
])
def test_unknown_usb_capability_never_attempts_a_write(replies):
    transport = FakeTransport(replies)
    modem = Modem("FAKE", transport=transport)
    with pytest.raises(UnsupportedModemError):
        modem.connect_usb_data()
    assert not any(command.startswith("AT+QNETDEVCTL=") and command != "AT+QNETDEVCTL=?" for command in transport.commands)


def test_ec200a_usb_control_uses_standard_a_documented_protocol_after_query():
    transport = FakeTransport({"AT+CGMM": ["EC200A"], "AT+QNETDEVCTL?": ["+QNETDEVCTL: 0,0,0,0"]})
    modem = Modem("FAKE", transport=transport)
    assert modem.usb_data_status()["supported"] is True
    assert modem.disconnect_usb_data()["requested"]
    assert transport.commands[-2:] == ["AT+QNETDEVCTL?", "AT+QNETDEVCTL=0,1,0"]


@pytest.mark.parametrize("context_id", [0, 16, -1, True, "1"])
def test_invalid_usb_context_is_rejected_before_io(context_id):
    transport = FakeTransport()
    with pytest.raises(ValueError):
        Modem("FAKE", transport=transport).connect_usb_data(context_id)
    assert transport.commands == []


def test_usb_write_must_match_firmware_advertised_capabilities():
    transport = FakeTransport({"AT+QNETDEVCTL=?": ["+QNETDEVCTL: (0),(1-15),(0-1)"]})
    with pytest.raises(UnsupportedModemError):
        Modem("FAKE", transport=transport).connect_usb_data()
    assert "AT+QNETDEVCTL=1,1,1" not in transport.commands


def test_initializer_uses_numeric_errors_supported_by_ec801e():
    transport = FakeTransport({"AT+CMEE=2": ATCommandError("AT+CMEE=2", "ERROR")})
    with Modem("FAKE", transport=transport):
        assert transport.commands[:3] == ["AT", "ATE0", "AT+CMEE=1"]
    assert "AT+CMEE=2" not in transport.commands


def test_qnwinfo_supplies_plmn_for_ec801e_blank_cops_without_guessing_operator_name():
    transport = FakeTransport({"AT+COPS?": ["+COPS: 0,,"], "AT+QNWINFO": ['+QNWINFO: "FDD LTE",23430,"LTE BAND 3",1617']})
    result = Modem("FAKE", transport=transport).status()
    assert result["operator"]["name"] == "23430"
    assert result["operator"]["source"] == "QNWINFO"
    assert result["radio"]["technology"] == "FDD LTE"
    assert result["radio"]["operator_plmn"] == "23430"
    assert result["radio"]["band"] == "LTE BAND 3"
    assert result["radio"]["channel"] == 1617


def test_qnwinfo_preserves_named_cops_operator_and_leading_zero_plmn():
    transport = FakeTransport({"AT+COPS?": ['+COPS: 0,0,"Example network",7'], "AT+QNWINFO": ['+QNWINFO: "FDD LTE","00101","LTE BAND 3",1617']})
    result = Modem("FAKE", transport=transport).status()
    assert result["operator"]["name"] == "Example network"
    assert result["operator"]["plmn"] == "00101"


@pytest.mark.parametrize("response,reason", [
    (ATCommandError("AT+QNWINFO", "ERROR"), "radio_query_failed"),
    (['+QNWINFO: "NONE"'], "radio_no_service"),
    (['+QNWINFO: "FDD LTE",not-a-plmn,"LTE BAND 3",unknown'], "radio_invalid_response"),
])
def test_optional_radio_query_failure_does_not_break_device_status(response, reason):
    result = Modem("FAKE", transport=FakeTransport({"AT+QNWINFO": response})).status()
    assert result["identity"]["supported"]
    assert result["radio"]["available"] is False
    assert result["radio"]["reason_code"] == reason
