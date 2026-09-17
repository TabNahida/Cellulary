"""High-level Quectel EC200A / EC801E operations.

PDP operations affect the module only. They do not install Windows network
drivers, configure a host adapter, change routes or connect the PC to the
Internet. Voice commands require suitable firmware, SIM service and audio
hardware; the EC801E voice capability is not established by its specification.
"""

from __future__ import annotations

import csv
import re
import threading
from collections.abc import Callable

from .errors import ATCommandError, PDUError, SMSDeliveryError, UnsupportedModemError
from .models import PROFILES, ATResponse
from .sms import decode_sms, encode_sms, reassemble_sms, validate_number
from .transport import ATTransport


def _fields(line: str) -> list[str]:
    return next(csv.reader([line.split(":", 1)[1].strip()], skipinitialspace=True))


def _integer(value: str, default=None):
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


class Modem:
    """A synchronous, thread-safe high-level client for a single AT port."""

    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 5.0, *, serial_factory: Callable | None = None, transport: ATTransport | None = None):
        self.port = port
        self.transport = transport or ATTransport(port, baudrate, timeout, serial_factory=serial_factory)
        self._lock = threading.RLock()
        self._identity: dict | None = None

    def open(self) -> Modem:
        with self._lock:
            self.transport.open()
            try:
                self.transport.command("AT")
                self.transport.command("ATE0")
                self.transport.command("AT+CMEE=2")
            except Exception:
                self.transport.close()
                raise
            self._identity = None
            return self

    def close(self) -> None:
        with self._lock:
            self.transport.close()
            self._identity = None

    def __enter__(self) -> Modem:
        return self.open()

    def __exit__(self, *_exc) -> None:
        self.close()

    def _command(self, command: str, *, timeout: float | None = None) -> ATResponse:
        match = re.match(r"AT(\+[A-Z0-9]+)", command)
        prefixes = (match[1] + ":",) if match else ()
        return self.transport.command(command, timeout=timeout, expected_prefixes=prefixes)

    def identify(self, *, refresh: bool = False) -> dict:
        with self._lock:
            if self._identity is not None and not refresh:
                return dict(self._identity)
            values = {}
            for key, command in (("manufacturer", "AT+CGMI"), ("model", "AT+CGMM"), ("revision", "AT+CGMR"), ("imei", "AT+CGSN")):
                values[key] = "\n".join(self._command(command).lines).strip()
            model = values["model"].upper()
            profile = next((p for p in PROFILES if re.search(rf"\b{re.escape(p.model_prefix)}(?:\b|[-_])", model)), None)
            if "QUECTEL" not in values["manufacturer"].upper():
                profile = None
            values.update(port=self.port, profile=profile.name if profile else None, supported=profile is not None, capabilities=list(profile.capabilities) if profile else [], voice_support="firmware_dependent" if profile else "unknown")
            self._identity = values
            return dict(values)

    def _supported(self) -> None:
        identity = self.identify()
        if not identity["supported"]:
            raise UnsupportedModemError(f"No supported profile for {identity['manufacturer']} {identity['model']}")

    def status(self) -> dict:
        with self._lock:
            result: dict = {"identity": self.identify(), "sim": {"state": "unknown"}, "signal": {}, "registration": {}, "operator": {}, "errors": []}
            try:
                lines = self._command("AT+CPIN?").lines
                state = next((line.split(":", 1)[1].strip() for line in lines if line.startswith("+CPIN:")), "UNKNOWN")
                result["sim"] = {"state": "ready" if state == "READY" else state.lower().replace(" ", "_"), "raw": state}
            except ATCommandError as exc:
                description = exc.result.lower()
                if re.search(r"error:\s*10$", description) or "sim not inserted" in description:
                    result["sim"] = {"state": "absent", "raw": exc.result}
                elif re.search(r"error:\s*13$", description) or "sim failure" in description:
                    result["sim"] = {"state": "failure", "raw": exc.result}
                else:
                    result["sim"] = {"state": "unknown", "error": exc.result}
                    result["errors"].append({"command": exc.command, "error": exc.result})
            try:
                for line in self._command("AT+CSQ").lines:
                    if line.startswith("+CSQ:"):
                        fields = _fields(line)
                        rssi, ber = _integer(fields[0]), _integer(fields[1])
                        result["signal"] = {"rssi": rssi, "ber": ber, "dbm": -113 + 2 * rssi if rssi is not None and 0 <= rssi <= 31 else None}
            except ATCommandError as exc:
                result["errors"].append({"command": exc.command, "error": exc.result})
            for command in ("AT+CEREG?", "AT+CREG?"):
                try:
                    for line in self._command(command).lines:
                        if line.startswith(("+CEREG:", "+CREG:")):
                            fields = _fields(line)
                            state = _integer(fields[1] if len(fields) > 1 else fields[0])
                            result["registration"] = {"status": state, "registered": state in (1, 5), "roaming": state == 5, "technology": _integer(fields[4]) if len(fields) > 4 else None}
                    break
                except ATCommandError as exc:
                    if command == "AT+CREG?":
                        result["errors"].append({"command": exc.command, "error": exc.result})
            try:
                for line in self._command("AT+COPS?").lines:
                    if line.startswith("+COPS:"):
                        fields = _fields(line)
                        result["operator"] = {"mode": _integer(fields[0]), "format": _integer(fields[1]) if len(fields) > 1 else None, "name": fields[2] if len(fields) > 2 else None, "technology": _integer(fields[3]) if len(fields) > 3 else None}
            except ATCommandError as exc:
                result["errors"].append({"command": exc.command, "error": exc.result})
            result["data"] = self.data_status()
            return result

    def list_sms(self, status: str = "ALL", *, reassemble: bool = True) -> list[dict]:
        """Read the current SMS storage; modem firmware may mark messages read."""
        statuses = {"REC UNREAD": 0, "REC READ": 1, "STO UNSENT": 2, "STO SENT": 3, "ALL": 4}
        normalized = status.upper()
        if normalized not in statuses:
            raise ValueError("Invalid SMS storage status")
        with self._lock:
            self._supported()
            self._command("AT+CMGF=0")
            response = self._command(f"AT+CMGL={statuses[normalized]}", timeout=30)
            result = []
            pending = None
            for line in response.lines:
                if line.startswith("+CMGL:"):
                    fields = _fields(line)
                    pending = {"index": int(fields[0]), "status": _integer(fields[1], fields[1])}
                elif pending is not None and re.fullmatch(r"[0-9A-Fa-f]+", line):
                    try:
                        pending.update(decode_sms(line))
                    except PDUError as exc:
                        pending.update(pdu=line, text=None, decode_error=str(exc))
                    result.append(pending)
                    pending = None
            return reassemble_sms(result) if reassemble else result

    def enable_sms_notifications(self) -> dict:
        """Request +CMTI storage notifications; drain_urcs() retrieves events.

        Polling list_sms() also works without this setting. Firmware controls
        whether the CNMI setting persists after a reboot.
        """
        with self._lock:
            self._supported()
            self._command("AT+CNMI=2,1,0,0,0")
            return {"enabled": True, "notification": "+CMTI", "delivery": "stored"}

    def send_sms(self, number: str, text: str) -> dict:
        parts = encode_sms(number, text)
        with self._lock:
            self._supported()
            self._command("AT+CMGF=0")
            references: list[int] = []
            for part in parts:
                try:
                    response = self.transport.prompt_command(f"AT+CMGS={part['tpdu_length']}", part["pdu"].encode("ascii"), timeout=120)
                    reference = next((int(line.split(":", 1)[1].strip()) for line in response.lines if line.startswith("+CMGS:")), None)
                    if reference is None:
                        raise PDUError("SMS returned OK without a message reference; submission outcome is unknown")
                    references.append(reference)
                except Exception as exc:
                    raise SMSDeliveryError(f"SMS submission stopped at segment {part['sequence']}/{part['total']}: {exc}. Do not retry automatically; sent segments or a timed-out segment may already have been delivered.", list(references), len(parts)) from exc
            return {"number": number, "segments": len(parts), "references": references, "encoding": parts[0]["encoding"], "status": "submitted"}

    def dial(self, number: str) -> dict:
        validate_number(number)
        with self._lock:
            self._supported()
            self._command(f"ATD{number};", timeout=60)
            return {"status": "dial_requested", "number": number}

    def answer(self) -> dict:
        with self._lock:
            self._supported()
            self._command("ATA", timeout=60)
            return {"status": "answer_requested"}

    def hangup(self) -> dict:
        with self._lock:
            self._supported()
            self._command("ATH")
            return {"status": "hangup_requested"}

    def list_calls(self) -> list[dict]:
        with self._lock:
            self._supported()
            result = []
            for line in self._command("AT+CLCC").lines:
                if line.startswith("+CLCC:"):
                    fields = _fields(line)
                    if len(fields) >= 5:
                        result.append({"index": _integer(fields[0]), "direction": "incoming" if fields[1] == "1" else "outgoing", "state": _integer(fields[2]), "mode": _integer(fields[3]), "multiparty": fields[4] == "1", "number": fields[5] if len(fields) > 5 else None})
            return result

    def data_status(self) -> dict:
        with self._lock:
            result: dict = {"attached": None, "contexts": [], "scope": "modem", "host_network_managed": False, "errors": []}
            contexts: dict[int, dict] = {}
            for command in ("AT+CGATT?", "AT+CGDCONT?", "AT+CGACT?", "AT+CGPADDR"):
                try:
                    lines = self._command(command).lines
                except ATCommandError as exc:
                    result["errors"].append({"command": exc.command, "error": exc.result})
                    continue
                for line in lines:
                    if line.startswith("+CGATT:"):
                        result["attached"] = line.split(":", 1)[1].strip() == "1"
                    elif line.startswith("+CGDCONT:"):
                        fields = _fields(line)
                        if len(fields) >= 4:
                            cid = int(fields[0])
                            contexts.setdefault(cid, {"context_id": cid, "active": None, "address": None, "addresses": []}).update(pdp_type=fields[1], apn=fields[2], configured_address=fields[3])
                    elif line.startswith("+CGACT:"):
                        fields = _fields(line)
                        cid = int(fields[0])
                        contexts.setdefault(cid, {"context_id": cid, "address": None, "addresses": []}).update(active=fields[1] == "1")
                    elif line.startswith("+CGPADDR:"):
                        fields = _fields(line)
                        cid = int(fields[0])
                        addresses = [address for address in fields[1:] if address and address not in ("0.0.0.0", "::", "0:0:0:0:0:0:0:0", ".".join(["0"] * 16))]
                        contexts.setdefault(cid, {"context_id": cid, "active": None}).update(address=addresses[0] if addresses else None, addresses=addresses)
            result["contexts"] = [contexts[cid] for cid in sorted(contexts)]
            return result

    @staticmethod
    def _context(context_id: int) -> None:
        if isinstance(context_id, bool) or not isinstance(context_id, int) or not 1 <= context_id <= 16:
            raise ValueError("PDP context ID must be an integer between 1 and 16")

    def configure_apn(self, apn: str, context_id: int = 1, pdp_type: str = "IP") -> dict:
        self._context(context_id)
        if not isinstance(apn, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", apn):
            raise ValueError("APN must contain 1–100 letters, digits, dots, underscores or hyphens")
        if pdp_type not in ("IP", "IPV6", "IPV4V6"):
            raise ValueError("PDP type must be IP, IPV6 or IPV4V6")
        with self._lock:
            self._supported()
            self._command(f'AT+CGDCONT={context_id},"{pdp_type}","{apn}"')
            return {"context_id": context_id, "apn": apn, "pdp_type": pdp_type, "scope": "modem"}

    def activate_data(self, context_id: int = 1) -> dict:
        self._context(context_id)
        with self._lock:
            self._supported()
            self._command(f"AT+CGACT=1,{context_id}", timeout=150)
            return {"context_id": context_id, "active": True, "scope": "modem", "host_network_managed": False}

    def deactivate_data(self, context_id: int = 1) -> dict:
        self._context(context_id)
        with self._lock:
            self._supported()
            self._command(f"AT+CGACT=0,{context_id}", timeout=40)
            return {"context_id": context_id, "active": False, "scope": "modem", "host_network_managed": False}

    @staticmethod
    def _usb_capabilities(line: str) -> dict | None:
        """Parse the three documented QNETDEVCTL test-response range groups."""
        match = re.fullmatch(r"\+QNETDEVCTL:\s*\(([^()]*)\)\s*,\s*\(([^()]*)\)\s*,\s*\(([^()]*)\)\s*", line)
        if match is None:
            return None
        groups = []
        for group in match.groups():
            values = set()
            for item in group.split(","):
                bounds = re.fullmatch(r"\s*(\d+)(?:\s*-\s*(\d+))?\s*", item)
                if bounds is None:
                    return None
                start, end = int(bounds[1]), int(bounds[2] or bounds[1])
                if not 0 <= start <= end <= 255:
                    return None
                values.update(range(start, end + 1))
            groups.append(sorted(values))
        return dict(zip(("operations", "context_ids", "urc_values"), groups, strict=True))

    def usb_data_status(self) -> dict:
        """Read EC801E USB data control state, without changing USB mode.

        QNETDEVCTL state describes the module-side data connection. Even state
        1 does not establish host DHCP, DNS, routes or Internet reachability.
        A supported test response can establish command availability on
        firmware where the read form is unavailable, with state left unknown.
        """
        with self._lock:
            identity = self.identify()
            result: dict = {"supported": False, "operation": None, "cid": None, "urc": None, "state": None, "connected": None, "raw": [], "scope": "usb_modem", "host_network_managed": False}
            if identity["profile"] != "quectel-ec801e":
                result["reason"] = "USB data control is currently verified only for the Quectel EC801E profile"
                return result
            try:
                result["raw"] = list(self._command("AT+QNETDEVCTL?").lines)
                for line in result["raw"]:
                    if not line.startswith("+QNETDEVCTL:"):
                        continue
                    fields = _fields(line)
                    values = [_integer(value) for value in fields[:4]]
                    if len(values) == 4 and all(value is not None for value in values):
                        operation, cid, urc, state = values
                        result.update(supported=True, operation=operation, cid=cid, urc=urc, state=state, connected={0: False, 1: True}.get(state), evidence="query")
                        if len(fields) > 4:
                            result["extra_fields"] = fields[4:]
                        return result
            except ATCommandError as exc:
                result["query_error"] = exc.result
            try:
                result["capability_raw"] = list(self._command("AT+QNETDEVCTL=?").lines)
                for line in result["capability_raw"]:
                    capabilities = self._usb_capabilities(line)
                    if capabilities is not None:
                        result.update(supported=True, capabilities=capabilities, evidence="test")
                        return result
            except ATCommandError as exc:
                result["test_error"] = exc.result
            result["reason"] = "Firmware did not return a recognized QNETDEVCTL query or capability response"
            return result

    def _request_usb_data(self, context_id: int, *, connect: bool) -> dict:
        if isinstance(context_id, bool) or not isinstance(context_id, int) or not 1 <= context_id <= 15:
            raise ValueError("USB data context ID must be an integer between 1 and 15")
        with self._lock:
            capability = self.usb_data_status()
            if not capability["supported"]:
                raise UnsupportedModemError(capability["reason"])
            operation = 1 if connect else 0
            capabilities = capability.get("capabilities")
            if capabilities is not None and (operation not in capabilities["operations"] or context_id not in capabilities["context_ids"] or operation not in capabilities["urc_values"]):
                raise UnsupportedModemError("Firmware does not advertise the requested USB data operation or context")
            self._command(f"AT+QNETDEVCTL={operation},{context_id},{operation}", timeout=60 if connect else 40)
            return {"status": "connect_requested" if connect else "disconnect_requested", "requested": True, "context_id": context_id, "connected": None, "scope": "usb_modem", "host_network_managed": False}

    def connect_usb_data(self, context_id: int = 1) -> dict:
        """Request EC801E USB data connectivity using the existing APN.

        Official EC801E guidance uses AT+QNETDEVCTL=1,<cid>,1. This neither
        changes usbnet mode nor restarts the modem or runs host DHCP.
        """
        return self._request_usb_data(context_id, connect=True)

    def disconnect_usb_data(self, context_id: int = 1) -> dict:
        """Request EC801E USB data disconnect with AT+QNETDEVCTL=0,<cid>,0."""
        return self._request_usb_data(context_id, connect=False)

    def drain_urcs(self) -> list[str]:
        return self.transport.drain_urcs()
