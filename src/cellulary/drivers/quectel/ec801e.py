"""EC801E driver: data support, firmware-gated SMS, no voice/GNSS.

Standard E AT V1.3 p95 explicitly excludes EC801E SMS. New firmware may add
it, so only an explicit CMGF capability response enables SMS operations.
The E audio guide excludes EC801E; its hardware manual lists no GNSS/audio.
"""

import re

from ...errors import ATCommandError, UnsupportedModemError
from ...models import ModemProfile
from ..base import register_driver
from .base import QnetdevDriver


@register_driver
class EC801EDriver(QnetdevDriver):
    profile = ModemProfile("quectel-ec801e", "EC801E", ("pdp", "subscriber_numbers", "usb_data"))
    model_pattern = r"\bEC801E(?:\b|[-_]|CN)"
    sms_support = "firmware_dependent"
    verification = "identification_status_tested"

    def _sms_capability(self) -> tuple[bool, str | None]:
        try:
            response = self.command("AT+CMGF=?")
        except ATCommandError as exc:
            return False, f"This EC801E firmware rejects SMS capability queries ({exc.result}); the Standard E manual excludes EC801E SMS"
        for line in response.lines:
            match = re.fullmatch(r"\+CMGF:\s*\(([^()]*)\)\s*", line)
            if match and any(re.fullmatch(r"\s*0(?:\s*[-–]\s*1)?\s*", item) for item in match[1].split(",")):
                return True, None
        return False, "This EC801E firmware has not advertised SMS PDU mode (CMGF=0)"

    def metadata(self) -> dict:
        result = super().metadata()
        supported, reason = self._sms_capability()
        result.update(sms_support="supported" if supported else "unsupported", sms_reason=reason, sms_reason_code=None if supported else "sms_firmware_unsupported", voice_reason="EC801E is excluded from the Standard E audio guide and exposes no documented voice/audio interface")
        if supported:
            result["capabilities"].append("sms")
        return result

    def require_sms(self) -> None:
        supported, reason = self._sms_capability()
        if not supported:
            raise UnsupportedModemError(reason)

    def gnss_status(self) -> dict:
        return {"supported": False, "enabled": None, "fix": False, "reason_code": "gnss_not_supported", "reason": "EC801E-CN has no documented integrated GNSS hardware or GNSS antenna interface"}
