"""Shared Quectel behavior; concrete models opt in to individual features."""

from __future__ import annotations

import re

from ...errors import ATCommandError, UnsupportedModemError
from ..base import ModemDriver, fields


class QuectelDriver(ModemDriver):
    manufacturer_pattern = r"\bQUECTEL\b"

    def network_info(self) -> dict:
        """Optional QNWINFO query; PLMN is kept numeric, never guessed as a brand."""
        result: dict = {"supported": False, "available": False, "technology": None, "operator_plmn": None, "band": None, "channel": None, "source": "QNWINFO", "raw": []}
        try:
            result["raw"] = list(self.command("AT+QNWINFO").lines)
        except ATCommandError as exc:
            return dict(result, error=exc.result, reason_code="radio_query_failed")
        for line in result["raw"]:
            if not line.startswith("+QNWINFO:"):
                continue
            values = fields(line)
            if values and values[0].upper() in ("NONE", "NO SERVICE"):
                return dict(result, supported=True, reason_code="radio_no_service")
            if len(values) >= 4:
                technology, plmn, band, channel = values[:4]
                if not re.fullmatch(r"\d{5,6}", plmn) or not re.fullmatch(r"\d+", channel):
                    continue
                return dict(result, supported=True, available=True, technology=technology, operator_plmn=plmn, band=band, channel=int(channel))
        return dict(result, reason_code="radio_invalid_response")

    def dial(self, number: str) -> dict:
        if self.voice_support == "unsupported":
            return super().dial(number)
        self.command(f"ATD{number};", timeout=60)
        return {"status": "dial_requested", "number": number}

    def answer(self) -> dict:
        if self.voice_support == "unsupported":
            return super().answer()
        self.command("ATA", timeout=60)
        return {"status": "answer_requested"}

    def hangup(self) -> dict:
        if self.voice_support == "unsupported":
            return super().hangup()
        self.command("AT+CHUP")
        return {"status": "hangup_requested"}

    def list_calls(self) -> list[dict]:
        if self.voice_support == "unsupported":
            return super().list_calls()
        result = []
        for line in self.command("AT+CLCC").lines:
            if line.startswith("+CLCC:"):
                values = fields(line)
                if len(values) >= 5:
                    result.append({"index": int(values[0]), "direction": "incoming" if values[1] == "1" else "outgoing", "state": int(values[2]), "mode": int(values[3]), "multiparty": values[4] == "1", "number": values[5] if len(values) > 5 else None})
        return result


class QnetdevDriver(QuectelDriver):
    """QNETDEVCTL USB data control documented for Standard A and E families."""

    @staticmethod
    def _usb_capabilities(line: str) -> dict | None:
        match = re.fullmatch(r"\+QNETDEVCTL:\s*\(([^()]*)\)\s*,\s*\(([^()]*)\)\s*,\s*\(([^()]*)\)\s*", line)
        if match is None:
            return None
        groups = []
        for group in match.groups():
            values = set()
            for item in group.split(","):
                bounds = re.fullmatch(r"\s*(\d+)(?:\s*[-–]\s*(\d+))?\s*", item)
                if bounds is None:
                    return None
                start, end = int(bounds[1]), int(bounds[2] or bounds[1])
                if not 0 <= start <= end <= 255:
                    return None
                values.update(range(start, end + 1))
            groups.append(sorted(values))
        return dict(zip(("operations", "context_ids", "urc_values"), groups, strict=True))

    def usb_data_status(self) -> dict:
        result: dict = {"supported": False, "operation": None, "cid": None, "urc": None, "state": None, "connected": None, "raw": [], "scope": "usb_modem", "host_network_managed": False}
        try:
            result["raw"] = list(self.command("AT+QNETDEVCTL?").lines)
            for line in result["raw"]:
                if not line.startswith("+QNETDEVCTL:"):
                    continue
                values = fields(line)
                if len(values) >= 4 and all(re.fullmatch(r"\d+", value) for value in values[:4]):
                    operation, cid, urc, state = map(int, values[:4])
                    result.update(supported=True, operation=operation, cid=cid, urc=urc, state=state, connected={0: False, 1: True}.get(state), evidence="query")
                    if len(values) > 4:
                        result["extra_fields"] = values[4:]
                    return result
        except ATCommandError as exc:
            result["query_error"] = exc.result
        try:
            result["capability_raw"] = list(self.command("AT+QNETDEVCTL=?").lines)
            for line in result["capability_raw"]:
                capabilities = self._usb_capabilities(line)
                if capabilities is not None:
                    result.update(supported=True, capabilities=capabilities, evidence="test")
                    return result
        except ATCommandError as exc:
            result["test_error"] = exc.result
        result["reason"] = "Firmware did not return a recognized QNETDEVCTL query or capability response"
        return result

    def request_usb_data(self, context_id: int, *, connect: bool) -> dict:
        capability = self.usb_data_status()
        if not capability["supported"]:
            raise UnsupportedModemError(capability["reason"])
        operation = 1 if connect else 0
        advertised = capability.get("capabilities")
        if advertised is not None and (operation not in advertised["operations"] or context_id not in advertised["context_ids"] or operation not in advertised["urc_values"]):
            raise UnsupportedModemError("Firmware does not advertise the requested USB data operation or context")
        self.command(f"AT+QNETDEVCTL={operation},{context_id},{operation}", timeout=60 if connect else 40)
        return {"status": "connect_requested" if connect else "disconnect_requested", "requested": True, "context_id": context_id, "connected": None, "scope": "usb_modem", "host_network_managed": False}
