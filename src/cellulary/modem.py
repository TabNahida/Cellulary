"""Thread-safe public modem facade with vendor/model driver delegation.

PDP operations affect the module only. They do not install Windows network
drivers, configure a host adapter, change routes or connect the PC to the
Internet. Voice commands require suitable firmware, SIM service and audio
hardware; the EC801E voice capability is not established by its specification.
"""

from __future__ import annotations

import csv
import re
import threading
import time
from collections.abc import Callable
from copy import deepcopy

from .drivers import ModemDriver, select_driver
from .errors import ATCommandError, PDUError, SMSDeliveryError, UnsupportedModemError
from .models import ATResponse
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
        self._driver: ModemDriver | None = None
        self._numbers: dict | None = None
        self._numbers_at = 0.0

    def open(self) -> Modem:
        with self._lock:
            self.transport.open()
            try:
                self.transport.command("AT")
                self.transport.command("ATE0")
                # EC801E documents only 0/1; numeric errors work across models.
                self.transport.command("AT+CMEE=1")
            except Exception:
                self.transport.close()
                raise
            self._identity = None
            self._driver = None
            self._numbers = None
            return self

    def close(self) -> None:
        with self._lock:
            self.transport.close()
            self._identity = None
            self._driver = None
            self._numbers = None

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
                return deepcopy(self._identity)
            values = {}
            for key, command in (("manufacturer", "AT+CGMI"), ("model", "AT+CGMM"), ("revision", "AT+CGMR"), ("imei", "AT+CGSN")):
                values[key] = "\n".join(self._command(command).lines).strip()
            self._driver = select_driver(values, self._command)
            values.update(port=self.port, **self._driver.metadata())
            self._identity = values
            self._numbers = None
            return deepcopy(values)

    @property
    def driver(self) -> ModemDriver:
        """The selected vendor/model adapter; first access identifies the module."""
        self.identify()
        assert self._driver is not None
        return self._driver

    def _supported(self) -> None:
        identity = self.identify()
        if not identity["supported"]:
            raise UnsupportedModemError(f"No supported profile for {identity['manufacturer']} {identity['model']}")

    def subscriber_numbers(self, *, refresh: bool = True) -> dict:
        """Read SIM-stored CNUM records; an empty response does not reveal a number.

        No IMSI, ICCID, IMEI, operator code or locally entered value is treated
        as a subscriber number. Status snapshots cache this query for 60 seconds.
        """
        with self._lock:
            self._supported()
            if not refresh and self._numbers is not None and time.monotonic() - self._numbers_at < 60:
                return deepcopy(self._numbers)
            result: dict = {"numbers": [], "primary": None, "source": "CNUM"}
            try:
                response = self._command("AT+CNUM")
                result["raw"] = list(response.lines)
                seen = set()
                for line in response.lines:
                    if not line.startswith("+CNUM:"):
                        continue
                    values = _fields(line)
                    if len(values) < 3:
                        continue
                    alpha, number, kind = values[0], values[1], _integer(values[2])
                    if not re.fullmatch(r"\+?[0-9]{1,32}", number):
                        continue
                    if kind is not None and kind & 0x70 == 0x10 and not number.startswith("+"):
                        number = "+" + number
                    key = (number, kind)
                    if key not in seen:
                        result["numbers"].append({"number": number, "alpha": alpha, "type": kind})
                        seen.add(key)
                if result["numbers"]:
                    result["primary"] = result["numbers"][0]["number"]
                else:
                    result["reason_code"] = "number_not_stored"
                    result["reason"] = "SIM does not expose a stored subscriber number; CNUM returned no usable number"
            except ATCommandError as exc:
                result.update(reason_code="number_query_failed", reason="Subscriber number is unavailable from this SIM or firmware", error=exc.result)
            self._numbers = deepcopy(result)
            self._numbers_at = time.monotonic()
            return result

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
            if result["sim"]["state"] == "ready" and result["identity"]["supported"]:
                numbers = self.subscriber_numbers(refresh=False)
                result["sim"].update(phone_number=numbers["primary"], numbers=numbers["numbers"], number_source=numbers["source"], number_reason=numbers.get("reason"), number_reason_code=numbers.get("reason_code"))
            else:
                self._numbers = None
                result["sim"].update(phone_number=None, numbers=[], number_source="CNUM", number_reason="SIM is not ready or the modem driver is unsupported", number_reason_code="sim_not_ready")
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
            result["radio"] = self.driver.network_info()
            plmn = result["radio"].get("operator_plmn")
            if plmn:
                result["operator"]["plmn"] = plmn
                if not result["operator"].get("name"):
                    result["operator"].update(name=plmn, format=2, source="QNWINFO")
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
            self.driver.require_sms()
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
            self.driver.require_sms()
            self._command("AT+CNMI=2,1,0,0,0")
            return {"enabled": True, "notification": "+CMTI", "delivery": "stored"}

    def send_sms(self, number: str, text: str) -> dict:
        parts = encode_sms(number, text)
        with self._lock:
            self._supported()
            self.driver.require_sms()
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
            return self.driver.dial(number)

    def answer(self) -> dict:
        with self._lock:
            self._supported()
            return self.driver.answer()

    def hangup(self) -> dict:
        with self._lock:
            self._supported()
            return self.driver.hangup()

    def list_calls(self) -> list[dict]:
        with self._lock:
            self._supported()
            return self.driver.list_calls()

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

    def usb_data_status(self) -> dict:
        """Read the selected driver's USB data state, without changing USB mode."""
        with self._lock:
            return self.driver.usb_data_status()

    def _request_usb_data(self, context_id: int, *, connect: bool) -> dict:
        if isinstance(context_id, bool) or not isinstance(context_id, int) or not 1 <= context_id <= 15:
            raise ValueError("USB data context ID must be an integer between 1 and 15")
        with self._lock:
            return self.driver.request_usb_data(context_id, connect=connect)

    def connect_usb_data(self, context_id: int = 1) -> dict:
        """Request USB data connectivity; APN, USB mode and host DHCP are unchanged."""
        return self._request_usb_data(context_id, connect=True)

    def disconnect_usb_data(self, context_id: int = 1) -> dict:
        """Request USB data disconnect through the selected driver."""
        return self._request_usb_data(context_id, connect=False)

    def gnss_status(self) -> dict:
        """Read GNSS availability, engine state and current fix where supported."""
        with self._lock:
            return self.driver.gnss_status()

    def gnss_location(self) -> dict:
        """Read a GNSS fix without automatically starting the receiver."""
        with self._lock:
            return self.driver.gnss_location()

    def start_gnss(self) -> dict:
        """Request standalone GNSS only after model and firmware capability checks."""
        with self._lock:
            return self.driver.start_gnss()

    def stop_gnss(self) -> dict:
        """Stop a supported GNSS receiver; unsupported models reject before writes."""
        with self._lock:
            return self.driver.stop_gnss()

    def drain_urcs(self) -> list[str]:
        return self.transport.drain_urcs()
