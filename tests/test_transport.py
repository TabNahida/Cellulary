import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from cellulary import ATCommandError, ATTimeoutError, ATTransport, TransportError


class FakeSerial:
    def __init__(self, script=None, **_kwargs):
        self.script = script or {}
        self.incoming = queue.Queue()
        self.writes = []
        self.closed = False

    @property
    def in_waiting(self):
        return self.incoming.qsize()

    def inject(self, data):
        for value in data:
            self.incoming.put(value)

    def read(self, size=1):
        try:
            first = self.incoming.get(timeout=0.01)
        except queue.Empty:
            return b""
        result = bytearray([first])
        while len(result) < size:
            try:
                result.append(self.incoming.get_nowait())
            except queue.Empty:
                break
        return bytes(result)

    def write(self, data):
        self.writes.append(data)
        reply = self.script.get(data, b"\r\nOK\r\n")
        if callable(reply):
            reply = reply(data)
        self.inject(reply)
        return len(data)

    def flush(self):
        pass

    def reset_input_buffer(self):
        while not self.incoming.empty():
            self.incoming.get_nowait()

    def close(self):
        self.closed = True


def connected(script=None, timeout=0.5):
    serial = FakeSerial(script)
    return ATTransport("FAKE", timeout=timeout, serial_factory=lambda **_: serial), serial


def test_echo_multiline_and_interleaved_urcs():
    transport, _ = connected({b"AT+CSQ\r": b'AT+CSQ\r\n+CMTI: "SM",2\r\nRING\r\n+CSQ: 23,99\r\nOK\r\n'})
    with transport:
        response = transport.command("AT+CSQ")
        assert response.lines == ["+CSQ: 23,99"]
        assert transport.drain_urcs() == ['+CMTI: "SM",2', "RING"]


def test_two_line_sms_urc_does_not_leak_into_response():
    transport, _ = connected({b"AT\r": b'\r\n+CMT: ,20\r\n001122AABB\r\nOK\r\n'})
    with transport:
        assert transport.command("AT").lines == []
        assert transport.drain_urcs() == ["+CMT: ,20", "001122AABB"]


def test_solicited_registration_is_not_treated_as_urc():
    transport, _ = connected({b"AT+CEREG?\r": b"\r\n+CEREG: 0,5\r\nOK\r\n"})
    with transport:
        assert transport.command("AT+CEREG?", expected_prefixes=("+CEREG:",)).lines == ["+CEREG: 0,5"]
        assert transport.drain_urcs() == []


@pytest.mark.parametrize("error", ["ERROR", "+CME ERROR: 10", "+CMS ERROR: 500"])
def test_command_error_is_reported_and_connection_remains_usable(error):
    transport, _ = connected({b"AT+BAD\r": f"\r\n{error}\r\n".encode()})
    with transport:
        with pytest.raises(ATCommandError) as caught:
            transport.command("AT+BAD")
        assert caught.value.result == error
        assert transport.command("AT").final == "OK"


def test_timeout_requires_reopen_and_prevents_late_response_reuse():
    transport, serial = connected({b"AT+SLOW\r": b""}, timeout=0.03)
    with transport:
        with pytest.raises(ATTimeoutError):
            transport.command("AT+SLOW")
        serial.inject(b"\r\nOK\r\n")
        with pytest.raises(TransportError, match="reopen"):
            transport.command("AT")
        assert serial.writes == [b"AT+SLOW\r"]


def test_sms_prompt_and_submission_are_atomic_against_other_commands():
    prompted = threading.Event()
    release_prompt = threading.Event()

    def prompt(_data):
        prompted.set()
        assert release_prompt.wait(1)
        return b"\r\n> "

    transport, serial = connected({b"AT+CMGS=12\r": prompt, b"0011\x1a": b"\r\n+CMGS: 7\r\nOK\r\n"})
    with transport, ThreadPoolExecutor(max_workers=2) as executor:
        sms = executor.submit(transport.prompt_command, "AT+CMGS=12", b"0011")
        assert prompted.wait(1)
        other = executor.submit(transport.command, "AT+CSQ")
        release_prompt.set()
        assert sms.result().lines == ["+CMGS: 7"]
        assert other.result().final == "OK"
        assert serial.writes == [b"AT+CMGS=12\r", b"0011\x1a", b"AT+CSQ\r"]


def test_reader_collects_idle_urcs():
    transport, serial = connected()
    with transport:
        serial.inject(b"RING\r\n")
        deadline = time.monotonic() + 1
        seen = []
        while not seen and time.monotonic() < deadline:
            seen.extend(transport.drain_urcs())
            time.sleep(0.002)
        assert seen == ["RING"]


def test_sms_ok_without_prompt_does_not_send_payload():
    transport, serial = connected()
    with transport:
        with pytest.raises(ATCommandError, match="Expected SMS prompt"):
            transport.prompt_command("AT+CMGS=12", b"0011")
        assert serial.writes == [b"AT+CMGS=12\r"]
