import pytest

from cellulary import PDUError, decode_sms, encode_sms, reassemble_sms


def test_known_gsm_deliver_pdu():
    sms = decode_sms("07919761989900F0040B919761556443F60000122080917324800AE8329BFD4697D9EC37")
    assert sms["text"] == "hellohello"
    assert sms["address"] == "+79165546346"
    assert sms["direction"] == "received"


def test_known_gsm_packed_payload_and_length():
    part, = encode_sms("+441234567890", "hellohello")
    assert part["pdu"].endswith("0AE8329BFD4697D9EC37")
    assert part["tpdu_length"] == len(bytes.fromhex(part["pdu"])) - 1


@pytest.mark.parametrize("text", ["中文短信，您好！", "£ hello € {} [] ~ \\ ^ |", "こんにちは", "😀你好🚀"])
def test_round_trip_text_and_number(text):
    parts = encode_sms("+8613800138000", text)
    assert "".join(decode_sms(part["pdu"])["text"] for part in parts) == text
    assert decode_sms(parts[0]["pdu"])["address"] == "+8613800138000"


@pytest.mark.parametrize("text,segments", [("a" * 160, 1), ("a" * 161, 2), ("€" * 80, 1), ("€" * 81, 2), ("中" * 70, 1), ("中" * 71, 2), ("😀" * 35, 1), ("😀" * 36, 2)])
def test_segmentation_boundaries(text, segments):
    parts = encode_sms("12345", text, reference=42)
    assert len(parts) == segments
    decoded = [decode_sms(part["pdu"]) for part in parts]
    assert "".join(sms["text"] for sms in decoded) == text
    if segments > 1:
        assert [sms["concatenation"] for sms in decoded] == [{"reference": 42, "total": segments, "sequence": i + 1} for i in range(segments)]


def test_extension_escape_and_surrogate_pairs_are_never_split():
    for text in ("a" * 152 + "€" * 10, "中" * 66 + "😀" * 10):
        decoded = [decode_sms(part["pdu"])["text"] for part in encode_sms("123", text)]
        assert "�" not in "".join(decoded)
        assert "".join(decoded) == text


@pytest.mark.parametrize("number", ["+12\rATD999;", "123;456", "++123", "abc", "", "+" + "1" * 21])
def test_reject_command_injection_and_invalid_addresses(number):
    with pytest.raises(ValueError):
        encode_sms(number, "test")


@pytest.mark.parametrize("pdu", ["", "xx", "0011000B91", "00FF"])
def test_truncated_or_invalid_pdu(pdu):
    with pytest.raises(PDUError):
        decode_sms(pdu)


def test_reassembly_orders_parts_and_keeps_storage_indices():
    original = "中文" * 80
    decoded = [dict(decode_sms(part["pdu"]), index=i + 1, status=1) for i, part in enumerate(encode_sms("123", original, reference=99))]
    assembled, = reassemble_sms(list(reversed(decoded)))
    assert assembled["text"] == original
    assert assembled["indices"] == [1, 2, 3]
    assert assembled["parts"] == decoded
    assert assembled["complete"] is True


def test_missing_or_ambiguous_parts_are_not_silently_combined():
    decoded = [decode_sms(part["pdu"]) for part in encode_sms("123", "中" * 71, reference=99)]
    missing, = reassemble_sms(decoded[:1])
    assert missing["complete"] is False
    assert missing["missing_parts"] == [2]
    duplicates = reassemble_sms([*decoded, decoded[0]])
    assert len(duplicates) == 3
    assert all(message["reassembly_error"] == "ambiguous_segments" for message in duplicates)


def test_reassembly_does_not_combine_messages_with_distant_timestamps():
    decoded = [decode_sms(part["pdu"]) for part in encode_sms("123", "中" * 71, reference=99)]
    decoded[0]["timestamp"] = "2026-09-01T12:00:00+00:00"
    decoded[1]["timestamp"] = "2026-09-03T12:00:00+00:00"
    assert len(reassemble_sms(decoded)) == 2
