"""EC25 QGPS adapter, covered by protocol tests, not physical hardware tests.

GNSS availability varies with EC25 SKU/firmware. A recognized QGPS read/test
response is required before enabling or stopping GNSS. Decimal coordinates
are requested explicitly using QGPSLOC=2; NMEA DDMM coordinates are not guessed.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone

from ...errors import ATCommandError, UnsupportedModemError
from ...models import ModemProfile
from ..base import fields, register_driver
from .base import QuectelDriver


def parse_qgpsloc(line: str) -> dict:
    """Parse QGPSLOC mode 2: UTC, lat, lon, HDOP, altitude, fix, COG, speeds, date, satellites."""
    values = fields(line)
    if len(values) != 11:
        raise ValueError("QGPSLOC=2 requires eleven response fields")
    latitude, longitude, hdop, altitude = map(float, values[1:5])
    fix_type = int(values[5])
    course, speed_kph, speed_knots = (float(value) if value else None for value in values[6:9])
    satellites = int(values[10])
    floats = (latitude, longitude, hdop, altitude, course, speed_kph, speed_knots)
    if any(value is not None and not math.isfinite(value) for value in floats):
        raise ValueError("QGPSLOC contains non-finite coordinates or measurements")
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180 and hdop >= 0 and satellites >= 0):
        raise ValueError("QGPSLOC contains out-of-range coordinates or measurements")
    if course is not None and not 0 <= course <= 360:
        raise ValueError("QGPSLOC course is out of range")
    if any(value is not None and value < 0 for value in (speed_kph, speed_knots)):
        raise ValueError("QGPSLOC speed is out of range")
    if not re.fullmatch(r"\d{6}(?:\.\d+)?", values[0]) or not re.fullmatch(r"\d{6}", values[9]):
        raise ValueError("QGPSLOC contains an invalid UTC date or time")
    utc, date = values[0], values[9]
    second = float(utc[4:])
    timestamp = datetime(2000 + int(date[4:6]), int(date[2:4]), int(date[:2]), int(utc[:2]), int(utc[2:4]), int(second), round((second % 1) * 1_000_000), tzinfo=timezone.utc)
    fixed = fix_type in (2, 3)
    result = {"fix": fixed, "fix_type": fix_type, "utc": utc, "date": date, "timestamp": timestamp.isoformat(), "latitude": latitude if fixed else None, "longitude": longitude if fixed else None, "hdop": hdop, "altitude_m": altitude if fixed else None, "course_deg": course, "speed_kph": speed_kph, "speed_knots": speed_knots, "satellites": satellites}
    if not fixed:
        result["reason_code"] = "gnss_no_fix"
        result["reason"] = "GNSS has not acquired a 2D or 3D fix"
    return result


@register_driver
class EC25Driver(QuectelDriver):
    profile = ModemProfile("quectel-ec25", "EC25", ("sms", "pdp", "subscriber_numbers", "voice", "gnss"))
    model_pattern = r"\bEC25(?:\b|[-_]|[AEJ][A-Z0-9]*\b)"
    sms_support = "supported"
    voice_support = "firmware_and_audio_hardware_dependent"
    gnss_support = "optional_probe_required"
    verification = "protocol_tests_only"

    def _gnss_state(self) -> dict:
        result: dict = {"supported": False, "enabled": None, "fix": False, "raw": [], "verification": self.verification}
        try:
            response = self.command("AT+QGPS?")
            result["raw"] = list(response.lines)
            for line in response.lines:
                match = re.fullmatch(r"\+QGPS:\s*([0-3])(?:\s*,.*)?", line)
                if match:
                    mode = int(match[1])
                    result.update(supported=True, enabled=mode != 0, mode=mode, evidence="query")
                    return result
        except ATCommandError as exc:
            result["query_error"] = exc.result
        try:
            response = self.command("AT+QGPS=?")
            result["capability_raw"] = list(response.lines)
            for line in response.lines:
                match = re.match(r"\+QGPS:\s*\(([^()]*)\)(?:\s*,.*)?$", line)
                if match:
                    # Standalone mode 1 is the only mode this API can start.
                    for item in match[1].split(","):
                        bounds = re.fullmatch(r"\s*(\d+)(?:\s*[-–]\s*(\d+))?\s*", item)
                        if bounds and int(bounds[1]) <= 1 <= int(bounds[2] or bounds[1]):
                            result.update(supported=True, evidence="test")
                            return result
        except ATCommandError as exc:
            result["test_error"] = exc.result
        result["reason_code"] = "gnss_firmware_unsupported"
        result["reason"] = "This EC25 SKU/firmware did not advertise a supported QGPS interface"
        return result

    def _location(self, state: dict) -> dict:
        if not state["supported"]:
            return state
        if state["enabled"] is False:
            return dict(state, reason_code="gnss_disabled", reason="GNSS is disabled")
        result = dict(state)
        try:
            response = self.command("AT+QGPSLOC=2")
        except ATCommandError as exc:
            result["error"] = exc.result
            no_fix = bool(re.search(r"\b516\b|not fixed|no fix", exc.result, re.I))
            result["reason_code"] = "gnss_no_fix" if no_fix else "gnss_query_failed"
            result["reason"] = "GNSS has not acquired a fix" if no_fix else f"GNSS location is unavailable: {exc.result}"
            return result
        result["location_raw"] = list(response.lines)
        for line in response.lines:
            if line.startswith("+QGPSLOC:"):
                try:
                    result.update(parse_qgpsloc(line))
                except (ValueError, OverflowError) as exc:
                    result["reason_code"] = "gnss_invalid_response"
                    result["reason"] = f"Invalid GNSS location response: {exc}"
                return result
        result["reason_code"] = "gnss_invalid_response"
        result["reason"] = "Firmware did not return a QGPSLOC location"
        return result

    def gnss_status(self) -> dict:
        # Status is safe to poll without acquiring precise location. Clients
        # explicitly call gnss_location() when they need coordinates.
        return self._gnss_state()

    def gnss_location(self) -> dict:
        return self._location(self._gnss_state())

    def start_gnss(self) -> dict:
        state = self._gnss_state()
        if not state["supported"]:
            raise UnsupportedModemError(state["reason"])
        if state["enabled"] is True:
            return dict(state, requested=False, status="already_enabled")
        self.command("AT+QGPS=1", timeout=10)
        return {"supported": True, "requested": True, "status": "start_requested", "enabled": None, "fix": False, "verification": self.verification}

    def stop_gnss(self) -> dict:
        state = self._gnss_state()
        if not state["supported"]:
            raise UnsupportedModemError(state["reason"])
        if state["enabled"] is False:
            return dict(state, requested=False, status="already_disabled")
        self.command("AT+QGPSEND", timeout=10)
        return {"supported": True, "requested": True, "status": "stop_requested", "enabled": None, "fix": False, "verification": self.verification}
