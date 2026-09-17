from test_modem import FakeTransport

from cellulary import ATCommandError, Modem


def test_cnum_parses_multiple_records_and_type_of_address():
    transport = FakeTransport({"AT+CNUM": ['+CNUM: "Primary, SIM","441234567890",145', '+CNUM: "Local","0201234567",129', '+CNUM: "duplicate","+441234567890",145']})
    result = Modem("FAKE", transport=transport).subscriber_numbers()
    assert result["primary"] == "+441234567890"
    assert result["source"] == "CNUM"
    assert result["numbers"] == [{"number": "+441234567890", "alpha": "Primary, SIM", "type": 145}, {"number": "0201234567", "alpha": "Local", "type": 129}]


def test_empty_ok_is_unknown_and_never_falls_back_to_identity_digits():
    modem = Modem("FAKE", transport=FakeTransport())
    result = modem.subscriber_numbers()
    assert result["primary"] is None
    assert result["numbers"] == []
    assert result["reason_code"] == "number_not_stored"


def test_unavailable_cnum_is_reported_without_guessing_or_phonebook_mutations():
    transport = FakeTransport({"AT+CNUM": ATCommandError("AT+CNUM", "ERROR")})
    result = Modem("FAKE", transport=transport).subscriber_numbers()
    assert result["primary"] is None
    assert result["reason_code"] == "number_query_failed"
    assert not any(command.startswith(("AT+CPBS", "AT+CPBR", "AT+CPBW")) for command in transport.commands)


def test_status_caches_cnum_and_clears_it_when_sim_is_removed():
    transport = FakeTransport({"AT+CPIN?": ["+CPIN: READY"], "AT+CNUM": ['+CNUM: "","+441234567890",145']})
    modem = Modem("FAKE", transport=transport)
    first = modem.status()["sim"]
    assert first["phone_number"] == "+441234567890"
    assert first["number_source"] == "CNUM"
    modem.status()
    assert transport.commands.count("AT+CNUM") == 1
    transport.replies["AT+CPIN?"] = ATCommandError("AT+CPIN?", "+CME ERROR: 10")
    absent = modem.status()["sim"]
    assert absent["phone_number"] is None
    assert absent["number_reason_code"] == "sim_not_ready"
    transport.replies["AT+CPIN?"] = ["+CPIN: READY"]
    transport.replies["AT+CNUM"] = []
    assert modem.status()["sim"]["phone_number"] is None
    assert transport.commands.count("AT+CNUM") == 2


def test_subscriber_query_explicit_refresh_bypasses_status_cache():
    transport = FakeTransport({"AT+CNUM": []})
    modem = Modem("FAKE", transport=transport)
    modem.subscriber_numbers(refresh=False)
    transport.replies["AT+CNUM"] = ['+CNUM: "","+441234567890",145']
    assert modem.subscriber_numbers(refresh=False)["primary"] is None
    assert modem.subscriber_numbers()["primary"] == "+441234567890"
