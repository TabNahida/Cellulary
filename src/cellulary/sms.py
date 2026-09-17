"""3GPP SMS PDU encoding/decoding with GSM 7-bit and UTF-16 multipart SMS."""

from __future__ import annotations

import math
import re
import secrets
from datetime import datetime, timedelta, timezone

from .errors import PDUError

_GSM = "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞ\x1bÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
_GSM_ENCODE = {char: i for i, char in enumerate(_GSM) if char != "\x1b"}
_EXT = {10: "\f", 20: "^", 40: "{", 41: "}", 47: "\\", 60: "[", 61: "~", 62: "]", 64: "|", 101: "€"}
_EXT_ENCODE = {char: [27, index] for index, char in _EXT.items()}


def validate_number(number: str) -> str:
    if not isinstance(number, str) or not re.fullmatch(r"\+?[0-9]{1,20}", number):
        raise ValueError("Phone number must contain 1–20 digits, optionally prefixed with +")
    return number


def _address(number: str) -> tuple[int, int, bytes]:
    validate_number(number)
    digits = number.lstrip("+")
    padded = digits + ("F" if len(digits) % 2 else "")
    encoded = bytes(int(padded[i + 1] + padded[i], 16) for i in range(0, len(padded), 2))
    return len(digits), 0x91 if number.startswith("+") else 0x81, encoded


def _pack_septets(values: list[int], header: bytes = b"") -> bytes:
    start = math.ceil(len(header) * 8 / 7) * 7
    bits = int.from_bytes(header, "little")
    for index, value in enumerate(values):
        bits |= value << (start + index * 7)
    return bits.to_bytes(math.ceil((start + len(values) * 7) / 8), "little")


def _unpack_septets(data: bytes, count: int, start: int = 0) -> list[int]:
    bits = int.from_bytes(data, "little")
    return [(bits >> (start + index * 7)) & 127 for index in range(count)]


def _gsm_text(values: list[int]) -> str:
    result: list[str] = []
    escaped = False
    for value in values:
        if escaped:
            result.append(_EXT.get(value, "�"))
            escaped = False
        elif value == 27:
            escaped = True
        else:
            result.append(_GSM[value])
    if escaped:
        result.append("�")
    return "".join(result)


def encode_sms(number: str, text: str, *, reference: int | None = None) -> list[dict]:
    """Return submit PDUs and AT+CMGS lengths, excluding the SMSC prefix.

    Characters outside GSM 03.38 use UTF-16BE (DCS 08). Supplementary Unicode
    characters retain their surrogate pairs when splitting long messages.
    """
    address_length, address_type, address = _address(number)
    if not isinstance(text, str) or not text:
        raise ValueError("SMS text must not be empty")
    if reference is not None and not 0 <= reference <= 255:
        raise ValueError("Concatenation reference must be 0–255")
    gsm = all(char in _GSM_ENCODE or char in _EXT_ENCODE for char in text)
    if gsm:
        units = [[_GSM_ENCODE[char]] if char in _GSM_ENCODE else _EXT_ENCODE[char] for char in text]
        single_limit, multipart_limit, dcs, encoding = 160, 153, 0, "gsm7"
    else:
        try:
            units = [list(char.encode("utf-16-be")) for char in text]
        except UnicodeEncodeError as exc:
            raise ValueError("SMS text contains an unpaired Unicode surrogate") from exc
        single_limit, multipart_limit, dcs, encoding = 140, 134, 8, "ucs2"
    total_units = sum(len(unit) for unit in units)
    limit = single_limit if total_units <= single_limit else multipart_limit
    parts: list[list[int]] = [[]]
    for unit in units:
        if len(parts[-1]) + len(unit) > limit:
            parts.append([])
        parts[-1].extend(unit)
    if len(parts) > 255:
        raise ValueError("SMS exceeds 255 concatenated segments")
    reference = secrets.randbelow(256) if reference is None else reference
    result: list[dict] = []
    for sequence, part in enumerate(parts, start=1):
        header = bytes([5, 0, 3, reference, len(parts), sequence]) if len(parts) > 1 else b""
        body = _pack_septets(part, header) if gsm else header + bytes(part)
        udl = len(part) + math.ceil(len(header) * 8 / 7) if gsm else len(body)
        tpdu = bytes([0x51 if header else 0x11, 0, address_length, address_type]) + address + bytes([0, dcs, 0xAA, udl]) + body
        result.append({"pdu": (b"\x00" + tpdu).hex().upper(), "tpdu_length": len(tpdu), "sequence": sequence, "total": len(parts), "encoding": encoding})
    return result


class _Cursor:
    def __init__(self, data: bytes):
        self.data, self.position = data, 0

    def take(self, length: int) -> bytes:
        if length < 0 or self.position + length > len(self.data):
            raise PDUError("Truncated SMS PDU")
        result = self.data[self.position:self.position + length]
        self.position += length
        return result

    def byte(self) -> int:
        return self.take(1)[0]


def _decode_address(cursor: _Cursor) -> str:
    length, kind = cursor.byte(), cursor.byte()
    data = cursor.take((length + 1) // 2)
    if kind & 0x70 == 0x50:
        return _gsm_text(_unpack_septets(data, length * 4 // 7))
    digits = "".join(f"{value & 15:X}{value >> 4:X}" for value in data)[:length]
    return ("+" if kind & 0x70 == 0x10 else "") + digits


def _timestamp(data: bytes) -> str | None:
    def bcd(value: int) -> int:
        return (value & 15) * 10 + (value >> 4)

    values = [bcd(value) for value in data[:6]]
    year = values[0] + (1900 if values[0] >= 90 else 2000)
    offset = bcd(data[6] & 0xF7) * 15 * (-1 if data[6] & 8 else 1)
    try:
        return datetime(year, *values[1:], tzinfo=timezone(timedelta(minutes=offset))).isoformat()
    except ValueError:
        return None


def _decode_header(header: bytes) -> dict | None:
    position = 0
    concatenation = None
    while position < len(header):
        if position + 2 > len(header):
            raise PDUError("Truncated SMS user data header")
        kind, size = header[position:position + 2]
        position += 2
        value = header[position:position + size]
        if len(value) != size:
            raise PDUError("Truncated SMS user data header element")
        if kind == 0 and size == 3:
            concatenation = {"reference": value[0], "total": value[1], "sequence": value[2]}
        elif kind == 8 and size == 4:
            concatenation = {"reference": int.from_bytes(value[:2], "big"), "total": value[2], "sequence": value[3]}
        position += size
    return concatenation


def decode_sms(pdu: str) -> dict:
    """Decode SMS-DELIVER, SMS-SUBMIT or a basic delivery status report."""
    try:
        cursor = _Cursor(bytes.fromhex(pdu))
    except (TypeError, ValueError) as exc:
        raise PDUError("SMS PDU must be a hexadecimal string") from exc
    cursor.take(cursor.byte())  # Service centre address; use modem's configured SMSC.
    first = cursor.byte()
    message_type = first & 3
    result: dict = {"pdu": pdu.upper(), "timestamp": None, "concatenation": None}
    if message_type == 0:
        result["direction"] = "received"
        result["address"] = _decode_address(cursor)
        cursor.byte()  # protocol identifier
        dcs = cursor.byte()
        result["timestamp"] = _timestamp(cursor.take(7))
    elif message_type == 1:
        result["direction"] = "sent"
        result["message_reference"] = cursor.byte()
        result["address"] = _decode_address(cursor)
        cursor.byte()
        dcs = cursor.byte()
        validity_format = (first >> 3) & 3
        cursor.take({0: 0, 1: 7, 2: 1, 3: 7}[validity_format])
    elif message_type == 2:
        result.update(direction="status_report", message_reference=cursor.byte())
        result["address"] = _decode_address(cursor)
        result["timestamp"] = _timestamp(cursor.take(7))
        result["discharged_at"] = _timestamp(cursor.take(7))
        result["delivery_status"] = cursor.byte()
        result["text"] = ""
        result["encoding"] = None
        return result
    else:
        raise PDUError("Unsupported SMS PDU message type")
    # General coding group, message waiting groups, and class coding group.
    if dcs & 0xC0 == 0:
        if dcs & 0x20:
            raise PDUError("Compressed SMS is not supported")
        alphabet = (dcs >> 2) & 3
    elif dcs & 0xF0 in (0xC0, 0xD0, 0xE0):
        alphabet = 2 if dcs & 0xF0 == 0xE0 else 0
    elif dcs & 0xF0 == 0xF0:
        alphabet = 1 if dcs & 4 else 0
    else:
        raise PDUError(f"Unsupported SMS data coding scheme: {dcs:02X}")
    if alphabet == 3:
        raise PDUError("Reserved SMS alphabet")
    length = cursor.byte()
    data = cursor.take(math.ceil(length * 7 / 8) if alphabet == 0 else length)
    header_length = 0
    if first & 0x40:
        if not data:
            raise PDUError("Missing SMS user data header")
        header_length = data[0] + 1
        if header_length > len(data):
            raise PDUError("Truncated SMS user data header")
        result["concatenation"] = _decode_header(data[1:header_length])
    if alphabet == 0:
        header_septets = math.ceil(header_length * 8 / 7)
        if header_septets > length:
            raise PDUError("SMS user data header exceeds the message length")
        result.update(encoding="gsm7", text=_gsm_text(_unpack_septets(data, length - header_septets, header_septets * 7)))
    elif alphabet == 2:
        result.update(encoding="ucs2", text=data[header_length:].decode("utf-16-be", errors="replace"))
    else:
        result.update(encoding="binary", text=None, data_hex=data[header_length:].hex().upper())
    return result


def reassemble_sms(messages: list[dict]) -> list[dict]:
    """Combine complete, unambiguous multipart groups and retain source records.

    Reference numbers are small and can be reused. Duplicate segment numbers
    or timestamps more than 24 hours apart are treated as ambiguous rather
    than silently splicing unrelated messages. Incomplete groups stay separate.
    """
    groups: dict[tuple, list[tuple[int, dict]]] = {}
    output: list[tuple[int, dict]] = []
    for position, message in enumerate(messages):
        concat = message.get("concatenation")
        if not concat or not isinstance(message.get("text"), str):
            output.append((position, message))
            continue
        key = (message.get("address"), message.get("direction"), message.get("encoding"), concat.get("reference"), concat.get("total"))
        groups.setdefault(key, []).append((position, message))
    for key, group in groups.items():
        total = key[-1]
        sequences = [message["concatenation"].get("sequence") for _, message in group]
        valid = isinstance(total, int) and 1 <= total <= 255 and all(isinstance(sequence, int) and 1 <= sequence <= total for sequence in sequences)
        duplicate = len(sequences) != len(set(sequences))
        timestamps = []
        for _, message in group:
            if message.get("timestamp"):
                try:
                    parsed = datetime.fromisoformat(message["timestamp"])
                    if parsed.tzinfo is not None:
                        timestamps.append(parsed)
                except (ValueError, TypeError):
                    pass
        distant = bool(timestamps and max(timestamps) - min(timestamps) > timedelta(hours=24))
        complete = valid and not duplicate and not distant and len(sequences) == total
        if not complete:
            for position, message in group:
                record = dict(message, complete=False)
                record["missing_parts"] = sorted(set(range(1, total + 1)) - set(sequences)) if valid else []
                record["reassembly_error"] = "ambiguous_segments" if duplicate or distant else "invalid_header" if not valid else "missing_segments"
                output.append((position, record))
            continue
        ordered = sorted((message for _, message in group), key=lambda message: message["concatenation"]["sequence"])
        combined = dict(ordered[0])
        combined.update(text="".join(message["text"] for message in ordered), parts=ordered, complete=True, indices=[message["index"] for message in ordered if "index" in message])
        combined["concatenation"] = {"reference": key[-2], "total": total, "sequence": None}
        if any(message.get("status") == 0 for message in ordered):
            combined["status"] = 0
        output.append((min(position for position, _ in group), combined))
    return [message for _, message in sorted(output, key=lambda pair: pair[0])]
