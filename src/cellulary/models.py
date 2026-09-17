"""Small, JSON-friendly public data models."""

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class PortInfo:
    port: str
    description: str = ""
    hwid: str = ""
    vid: int | None = None
    pid: int | None = None
    serial_number: str | None = None
    location: str | None = None
    interface: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ATResponse:
    command: str
    lines: list[str] = field(default_factory=list)
    final: str = "OK"


@dataclass(frozen=True)
class ModemProfile:
    name: str
    model_prefix: str
    capabilities: tuple[str, ...] = ("sms", "pdp")


def __getattr__(name: str):
    # Compatibility for callers that previously inspected the static profiles.
    # The registry now owns model selection and behavior.
    if name == "PROFILES":
        from .drivers import registered_drivers

        return tuple(driver.profile for driver in registered_drivers())
    raise AttributeError(name)
