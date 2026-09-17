"""Serialized AT transactions with a background reader and bounded URC queue."""

from __future__ import annotations

import queue
import threading
import time
from collections import deque
from collections.abc import Callable

from .errors import ATCommandError, ATTimeoutError, TransportError
from .models import ATResponse

_ERRORS = ("ERROR", "+CME ERROR", "+CMS ERROR", "NO CARRIER", "NO ANSWER", "BUSY", "NO DIALTONE")
_URCS = ("+CMTI:", "+CMT:", "+CDS:", "+CBM:", "+CREG:", "+CGREG:", "+CEREG:", "+QIURC:", "+QIND:", "+QUSIM:", "+CPIN:", "+CLIP:", "+CRING:", "+QNETDEVSTATUS:")
_BARE_URCS = {"RING", "RDY", "APP RDY", "SMS DONE", "PB DONE", "SMS Ready", "Call Ready", "POWERED DOWN", "NO CARRIER"}


class ATTransport:
    """One connection per AT port; concurrent commands execute in order.

    A timeout poisons the connection, preventing a delayed final response from
    being mistaken for the result of another command on that connection.
    Reopening flushes already-buffered input; timed-out operations must never
    be automatically retried because they may still complete on the modem.
    """

    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 5.0, *, serial_factory: Callable | None = None):
        self.port, self.baudrate, self.timeout = port, baudrate, timeout
        self._factory = serial_factory
        self._serial = None
        self._reader: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._state_lock = threading.Lock()
        self._active: queue.Queue | None = None
        self._expected: tuple[str, ...] = ()
        self._urcs: deque[str] = deque(maxlen=1000)
        self._failed: str | None = None
        self._urc_body = False
        self._accept_call_final = False

    def open(self) -> ATTransport:
        with self._lock:
            if self._serial is not None:
                return self
            factory = self._factory
            if factory is None:
                import serial

                factory = serial.Serial
            try:
                self._serial = factory(port=self.port, baudrate=self.baudrate, timeout=0.1, write_timeout=self.timeout)
                # Remove stale responses from an earlier connection before reading.
                self._serial.reset_input_buffer()
            except Exception as exc:
                if self._serial is not None:
                    self._serial.close()
                    self._serial = None
                raise TransportError(f"Cannot open {self.port}: {exc}") from exc
            self._failed = None
            self._urc_body = False
            self._stop.clear()
            self._reader = threading.Thread(target=self._read_loop, name=f"AT-{self.port}", daemon=True)
            self._reader.start()
            return self

    def close(self) -> None:
        with self._lock:
            self._stop.set()
            if self._reader is not None:
                self._reader.join(timeout=1)
            if self._serial is not None:
                self._serial.close()
                self._serial = None
            self._reader = None

    def __enter__(self) -> ATTransport:
        return self.open()

    def __exit__(self, *_exc) -> None:
        self.close()

    def drain_urcs(self) -> list[str]:
        with self._state_lock:
            result = list(self._urcs)
            self._urcs.clear()
            return result

    def _dispatch(self, frame: str) -> None:
        if not frame:
            return
        with self._state_lock:
            if self._urc_body:
                self._urcs.append(frame)
                self._urc_body = False
                return
            known_urc = frame in _BARE_URCS or frame.startswith(_URCS)
            solicited = any(frame.startswith(prefix) for prefix in self._expected)
            if frame == "NO CARRIER" and self._accept_call_final:
                solicited = True
            if self._active is None or (known_urc and not solicited):
                self._urcs.append(frame)
                self._urc_body = frame.startswith(("+CMT:", "+CDS:", "+CBM:"))
            else:
                self._active.put(frame)

    def _read_loop(self) -> None:
        buffer = bytearray()
        try:
            while not self._stop.is_set():
                data = self._serial.read(max(1, min(getattr(self._serial, "in_waiting", 0), 4096)))
                for value in data:
                    if value in (10, 13):
                        if buffer:
                            self._dispatch(buffer.decode("utf-8", errors="replace").strip())
                            buffer.clear()
                    elif value == 62 and not buffer.strip():
                        self._dispatch(">")
                        buffer.clear()
                    else:
                        buffer.append(value)
                        if len(buffer) > 65536:
                            raise TransportError("AT response line exceeds 64 KiB")
        except Exception as exc:
            if not self._stop.is_set():
                with self._state_lock:
                    self._failed = f"Serial reader failed: {exc}"
                    if self._active is not None:
                        self._active.put(TransportError(self._failed))

    def _begin(self, command: str, expected_prefixes: tuple[str, ...]) -> queue.Queue:
        if not command.startswith("AT") or any(ord(char) < 32 or ord(char) == 127 for char in command):
            raise ValueError("An AT command must start with AT and contain no control delimiters")
        if self._serial is None:
            raise TransportError("Serial connection is closed")
        with self._state_lock:
            if self._failed:
                raise TransportError(self._failed + "; close and reopen the connection")
            events = queue.Queue()
            self._active = events
            self._expected = expected_prefixes
            self._accept_call_final = command.startswith(("ATD", "ATA", "ATH"))
        try:
            self._write(command.encode("ascii") + b"\r")
        except Exception:
            self._end()
            raise
        return events

    def _write(self, data: bytes) -> None:
        try:
            written = self._serial.write(data)
            if written != len(data):
                raise TransportError("Incomplete serial write")
            self._serial.flush()
        except Exception as exc:
            self._failed = f"Serial write failed: {exc}"
            raise TransportError(self._failed) from exc

    def _end(self) -> None:
        with self._state_lock:
            self._active = None
            self._expected = ()
            self._accept_call_final = False

    def _wait(self, events: queue.Queue, command: str, deadline: float, lines: list[str], *, prompt: bool = False) -> str:
        while True:
            remaining = deadline - time.monotonic()
            try:
                if remaining <= 0:
                    raise queue.Empty
                event = events.get(timeout=remaining)
            except queue.Empty:
                self._failed = f"Timed out waiting for {command}"
                raise ATTimeoutError(self._failed + "; close and reopen the connection") from None
            if isinstance(event, Exception):
                raise event
            if event == command:
                continue
            if any(event == error or event.startswith(error + ":") for error in _ERRORS):
                raise ATCommandError(command, event, list(lines))
            if event == ">" and prompt:
                return event
            if event == "OK" or event.startswith("CONNECT"):
                if prompt:
                    raise ATCommandError(command, "Expected SMS prompt, received " + event, list(lines))
                return event
            lines.append(event)

    def command(self, command: str, *, timeout: float | None = None, expected_prefixes: tuple[str, ...] = ()) -> ATResponse:
        with self._lock:
            events = self._begin(command, expected_prefixes)
            lines: list[str] = []
            try:
                final = self._wait(events, command, time.monotonic() + (self.timeout if timeout is None else timeout), lines)
                return ATResponse(command, lines, final)
            finally:
                self._end()

    def prompt_command(self, command: str, payload: bytes, *, timeout: float = 60.0) -> ATResponse:
        """Keep the transaction lock through prompt, payload, Ctrl-Z and result."""
        if b"\x1a" in payload or b"\x1b" in payload:
            raise ValueError("Payload must not contain SMS submission delimiters")
        with self._lock:
            events = self._begin(command, ("+CMGS:",))
            lines: list[str] = []
            deadline = time.monotonic() + timeout
            try:
                self._wait(events, command, deadline, lines, prompt=True)
                self._write(payload + b"\x1a")
                final = self._wait(events, command, deadline, lines)
                return ATResponse(command, lines, final)
            finally:
                self._end()
