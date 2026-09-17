"""Driver interface and registry; protocol ownership stays with Modem."""

from __future__ import annotations

import csv
import re
from collections.abc import Callable

from ..errors import UnsupportedModemError
from ..models import ModemProfile


def fields(line: str) -> list[str]:
    return next(csv.reader([line.split(":", 1)[1].strip()], skipinitialspace=True))


class ModemDriver:
    """Override features in vendor/model drivers, never in the public facade."""

    profile: ModemProfile | None = None
    manufacturer_pattern = r"(?!)"
    model_pattern = r"(?!)"
    voice_support = "unsupported"
    gnss_support = "unsupported"
    sms_support = "unsupported"
    verification = "unverified"

    def __init__(self, command: Callable, identity: dict):
        self.command = command
        self.identity = identity

    @classmethod
    def matches(cls, identity: dict) -> bool:
        return bool(re.search(cls.manufacturer_pattern, identity.get("manufacturer", ""), re.I) and re.search(cls.model_pattern, identity.get("model", ""), re.I))

    def metadata(self) -> dict:
        return {"driver": f"{type(self).__module__}.{type(self).__name__}", "profile": self.profile.name if self.profile else None, "supported": self.profile is not None, "capabilities": list(self.profile.capabilities) if self.profile else [], "voice_support": self.voice_support, "sms_support": self.sms_support, "gnss_support": self.gnss_support, "verification": self.verification}

    def require_sms(self) -> None:
        if self.sms_support != "supported":
            raise UnsupportedModemError("SMS is not supported by this modem driver")

    def dial(self, number: str) -> dict:
        raise UnsupportedModemError("Voice calls are not supported by this modem driver")

    def answer(self) -> dict:
        raise UnsupportedModemError("Voice calls are not supported by this modem driver")

    def hangup(self) -> dict:
        raise UnsupportedModemError("Voice calls are not supported by this modem driver")

    def list_calls(self) -> list[dict]:
        raise UnsupportedModemError("Voice calls are not supported by this modem driver")

    def network_info(self) -> dict:
        return {"supported": False, "available": False, "technology": None, "operator_plmn": None, "band": None, "channel": None, "reason_code": "radio_not_supported"}

    def usb_data_status(self) -> dict:
        return {"supported": False, "connected": None, "scope": "usb_modem", "host_network_managed": False, "reason": "USB data control is not implemented for this modem driver"}

    def request_usb_data(self, context_id: int, *, connect: bool) -> dict:
        raise UnsupportedModemError(self.usb_data_status()["reason"])

    def gnss_status(self) -> dict:
        return {"supported": False, "enabled": None, "fix": False, "reason_code": "gnss_not_supported", "reason": "This modem driver has no documented GNSS support"}

    def gnss_location(self) -> dict:
        return self.gnss_status()

    def start_gnss(self) -> dict:
        raise UnsupportedModemError(self.gnss_status()["reason"])

    def stop_gnss(self) -> dict:
        raise UnsupportedModemError(self.gnss_status()["reason"])


_DRIVERS: list[type[ModemDriver]] = []


def register_driver(driver: type[ModemDriver]) -> type[ModemDriver]:
    """Register an explicit manufacturer/model matcher; reject name collisions."""
    if driver.profile is None:
        raise ValueError("Registered drivers require a profile")
    if any(item.profile.name == driver.profile.name for item in _DRIVERS):
        raise ValueError(f"Driver profile already registered: {driver.profile.name}")
    _DRIVERS.append(driver)
    return driver


def registered_drivers() -> tuple[type[ModemDriver], ...]:
    return tuple(_DRIVERS)


def select_driver(identity: dict, command: Callable) -> ModemDriver:
    matches = [driver for driver in _DRIVERS if driver.matches(identity)]
    if len(matches) > 1:
        raise ValueError("Ambiguous modem identity matches multiple registered drivers")
    return (matches[0] if matches else ModemDriver)(command, identity)
