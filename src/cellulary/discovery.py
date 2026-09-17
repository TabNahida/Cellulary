"""Conservative enumeration: only explicitly labelled Quectel AT interfaces.

This module does not open serial ports. USB diagnostic, NMEA, modem/data and
unidentified interfaces are deliberately excluded, even for known USB IDs.
"""

import re
from collections.abc import Iterable

from .models import PortInfo


def is_quectel_at_port(port: object) -> bool:
    description = str(getattr(port, "description", "") or "")
    interface = str(getattr(port, "interface", "") or "")
    manufacturer = str(getattr(port, "manufacturer", "") or "")
    text = f"{description} {interface}"
    quectel = getattr(port, "vid", None) == 0x2C7C or "quectel" in f"{text} {manufacturer}".lower()
    if not quectel or re.search(r"\b(diag(?:nostic)?|nmea|debug|dm)\b", text, re.I):
        return False
    return bool(re.search(r"\bAT(?:\s*Port)?\b", text, re.I))


def discover_ports(ports: Iterable[object] | None = None) -> list[PortInfo]:
    if ports is None:
        from serial.tools import list_ports

        ports = list_ports.comports()
    found = [
        PortInfo(
            port=str(p.device),
            description=str(getattr(p, "description", "") or ""),
            hwid=str(getattr(p, "hwid", "") or ""),
            vid=getattr(p, "vid", None),
            pid=getattr(p, "pid", None),
            serial_number=getattr(p, "serial_number", None),
            location=getattr(p, "location", None),
            interface=getattr(p, "interface", None),
        )
        for p in ports
        if is_quectel_at_port(p)
    ]
    return sorted(found, key=lambda p: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", p.port)])
