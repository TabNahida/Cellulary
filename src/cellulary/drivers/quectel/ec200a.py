"""EC200A Standard A driver; EU has no integrated GNSS.

Sources: EC200A hardware design V1.3 §2.1/5.2; Standard A AT V1.4
§7 (voice) and §10.17 (QNETDEVCTL).
"""

import re

from ...models import ModemProfile
from ..base import register_driver
from .base import QnetdevDriver


@register_driver
class EC200ADriver(QnetdevDriver):
    profile = ModemProfile("quectel-ec200a", "EC200A", ("sms", "pdp", "subscriber_numbers", "voice", "usb_data"))
    model_pattern = r"\bEC200A(?:\b|[-_]|CN|EU|AU|EL)"
    sms_support = "supported"
    voice_support = "firmware_and_audio_hardware_dependent"
    verification = "identification_status_tested"

    def gnss_status(self) -> dict:
        identity = f"{self.identity.get('model', '')} {self.identity.get('revision', '')}".upper()
        if re.search(r"EC200A[-_]?EU", identity):
            reason = "EC200A-EU has no integrated GNSS; the hardware manual lists GNSS only as an EC200A-CN option"
        elif re.search(r"EC200A[-_]?CN", identity):
            reason = "EC200A-CN GNSS is optional; its GNSS command adapter is not yet verified and no GNSS commands are sent"
        else:
            reason = "Only EC200A-CN optionally includes GNSS; this variant has no verified GNSS command adapter"
        return {"supported": False, "enabled": None, "fix": False, "reason_code": "gnss_variant_not_supported", "reason": reason}
