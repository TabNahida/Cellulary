"""Thread-safe device ownership and cached snapshots shared by CLI and HTTP."""
from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from threading import Lock, RLock

from .discovery import discover_ports
from .errors import TransportError
from .modem import Modem


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DeviceManager:
    def __init__(self, *, discover=discover_ports, modem_factory=Modem):
        self._discover = discover
        self._factory = modem_factory
        self._lock = RLock()
        self._scan_lock = Lock()
        self._device_locks: dict[str, RLock] = {}
        self._closed = False
        self._modems: dict[str, Modem] = {}
        self._devices: dict[str, dict] = {}
        self._events = deque(maxlen=300)
        self.scanning = False
        self.demo = False

    def event(self, message: str, device_id: str | None = None, level: str = "info"):
        with self._lock:
            self._events.appendleft(dict(time=now(), level=level, device_id=device_id, message=message))

    def events(self):
        with self._lock:
            return {"events": list(self._events)}

    def snapshot(self):
        with self._lock:
            return {"devices": deepcopy(list(self._devices.values())), "scanning": self.scanning}

    def _device_lock(self, device_id):
        # Keep lock identities stable across unplug/replug and reconnect.
        with self._lock:
            return self._device_locks.setdefault(device_id, RLock())

    def _close_modem(self, modem, device_id):
        try:
            modem.__exit__(None, None, None)
        except Exception as exc:
            self.event(f"Could not close port: {exc}", device_id, "error")

    def _invalidate(self, device_id, exc):
        # Caller owns the device operation lock. Never wait on serial I/O while
        # holding the manager-wide lock: other devices must remain responsive.
        with self._lock:
            modem = self._modems.pop(device_id, None)
            if device_id in self._devices:
                self._devices[device_id].update(connected=False, error=str(exc), updated_at=now())
        if modem is not None:
            self._close_modem(modem, device_id)

    @staticmethod
    def _transport_failed(exc):
        seen = set()
        while exc is not None and id(exc) not in seen:
            seen.add(id(exc))
            if isinstance(exc, (TransportError, OSError)):
                return True
            exc = exc.__cause__ or exc.__context__
        return False

    def _read(self, device_id: str):
        with self._lock:
            if self._closed:
                raise KeyError(device_id)
            modem = self._modems[device_id]
        status = modem.status()
        for line in modem.drain_urcs():
            if line.startswith(("+CMTI:", "+CEREG:", "+CREG:", "+QIURC:")) or line in {"RING", "NO CARRIER", "RDY"}:
                self.event(line, device_id)
        identity = status.get("identity", {})
        registration = status.get("registration", {})
        operator = status.get("operator", {})
        sim = status.get("sim", {})
        normalized = dict(
            **identity, firmware=identity.get("revision"),
            sim_status=sim.get("state", "UNKNOWN"),
            phone_number=sim.get("phone_number"), numbers=sim.get("numbers", []),
            number_source=sim.get("number_source"), number_reason=sim.get("number_reason"),
            number_reason_code=sim.get("number_reason_code"),
            operator=operator.get("name") if isinstance(operator, dict) else operator,
            registration=registration, signal=status.get("signal", {}),
            radio=status.get("radio", {}),
            data=status.get("data", {}), connected=True, error=None, updated_at=now(),
            query_errors=status.get("errors", []),
        )
        with self._lock:
            self._devices[device_id].update(normalized)
            return deepcopy(self._devices[device_id])

    def _probe(self, port):
        device_id = port.port
        with self._device_lock(device_id):
            with self._lock:
                if self._closed:
                    return
                self._devices.setdefault(device_id, dict(asdict(port), id=device_id, connected=False))
                self._devices[device_id].update(asdict(port))
                exists = device_id in self._modems
            opening = None
            try:
                if not exists:
                    opening = self._factory(port.port)
                    opening.__enter__()
                    with self._lock:
                        self._modems[device_id] = opening
                    opening = None
                    self.event("Device connected", device_id)
                self._read(device_id)
            except Exception as exc:
                if opening is not None:
                    self._close_modem(opening, device_id)
                self._invalidate(device_id, exc)
                self.event(str(exc), device_id, "error")

    def scan(self):
        if not self._scan_lock.acquire(blocking=False):
            return self.snapshot()
        try:
            with self._lock:
                if self._closed:
                    return self.snapshot()
                self.scanning = True
            ports = self._discover()
            present = {p.port for p in ports}
            with self._lock:
                removed = [device_id for device_id in self._devices if device_id not in present]
            for device_id in removed:
                with self._device_lock(device_id):
                    with self._lock:
                        modem = self._modems.pop(device_id, None)
                        self._devices.pop(device_id, None)
                    if modem:
                        self._close_modem(modem, device_id)
                        self.event("Device removed", device_id, "warning")
            with ThreadPoolExecutor(max_workers=6) as pool:
                list(pool.map(self._probe, ports))
        finally:
            with self._lock:
                self.scanning = False
            self._scan_lock.release()
        return self.snapshot()

    def status(self, device_id):
        with self._device_lock(device_id):
            try:
                return self._read(device_id)
            except Exception as exc:
                if self._transport_failed(exc):
                    self._invalidate(device_id, exc)
                raise

    def invoke(self, device_id: str, method: str, **kwargs):
        with self._device_lock(device_id):
            with self._lock:
                if self._closed:
                    raise KeyError(device_id)
                modem = self._modems[device_id]
            try:
                result = getattr(modem, method)(**kwargs)
            except Exception as exc:
                if self._transport_failed(exc):
                    self._invalidate(device_id, exc)
                self.event(f"{method}: {exc}", device_id, "error")
                raise
            if method not in {"list_sms", "list_calls", "data_status", "usb_data_status", "subscriber_numbers", "gnss_status", "gnss_location"}:
                self.event(f"{method} completed", device_id)
            return result

    def close(self):
        with self._scan_lock:
            with self._lock:
                self._closed = True
                device_ids = list(self._modems)
            for device_id in device_ids:
                with self._device_lock(device_id):
                    with self._lock:
                        modem = self._modems.pop(device_id, None)
                        if device_id in self._devices:
                            self._devices[device_id].update(connected=False, updated_at=now())
                    if modem is not None:
                        self._close_modem(modem, device_id)
