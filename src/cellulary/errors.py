"""Errors raised by the modem protocol and public API."""


class CellularyError(Exception):
    """Base class for errors callers can safely display."""


class TransportError(CellularyError):
    """The serial connection is unavailable or no longer synchronized."""


class ATTimeoutError(TransportError):
    """A response timed out; close and reopen before sending another command."""


class ATCommandError(CellularyError):
    def __init__(self, command: str, result: str, lines: list[str] | None = None):
        self.command = command
        self.result = result
        self.lines = lines or []
        super().__init__(f"{command}: {result}")


class UnsupportedModemError(CellularyError):
    """An operation was requested on an unrecognized modem profile."""


class PDUError(CellularyError, ValueError):
    """An SMS PDU is malformed or uses an unsupported encoding."""


class SMSDeliveryError(CellularyError):
    """Submission failed, possibly after earlier multipart segments were sent."""

    def __init__(self, message: str, references: list[int], total_segments: int):
        self.references = references
        self.total_segments = total_segments
        super().__init__(message)
