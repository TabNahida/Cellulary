import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from cellulary.errors import ATCommandError, ATTimeoutError, SMSDeliveryError
from cellulary.manager import DeviceManager
from cellulary.models import PortInfo


class FakeModem:
    def __init__(self, port):
        self.port = port
        self.closed = False
        self.status_error = None
        self.send_error = None
        self.close_error = False
        self.operation_started = threading.Event()
        self.operation_release = threading.Event()
        self.send_count = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True
        if self.close_error:
            raise OSError("close failed")

    def status(self):
        if self.closed:
            raise AssertionError("I/O on a closed modem")
        if self.status_error:
            raise self.status_error
        return {"identity": {"model": "EC801E"}, "sim": {"state": "ready"}}

    def drain_urcs(self):
        return []

    def send_sms(self, **_kwargs):
        self.send_count += 1
        if self.send_error:
            raise self.send_error
        return {"status": "submitted"}

    def blocking_operation(self):
        self.operation_started.set()
        assert self.operation_release.wait(2)
        assert not self.closed
        return "done"


def setup_manager(ports=None):
    ports = [PortInfo("COM11")] if ports is None else ports
    instances = []

    def factory(port):
        modem = FakeModem(port)
        instances.append(modem)
        return modem

    manager = DeviceManager(discover=lambda: list(ports), modem_factory=factory)
    manager.scan()
    return manager, ports, instances


def test_timeout_invalidates_immediately_and_next_scan_reconnects_without_retry():
    manager, _, instances = setup_manager()
    first = instances[0]
    cause = ATTimeoutError("timed out")
    failure = SMSDeliveryError("submission outcome unknown", [], 1)
    failure.__cause__ = cause
    first.send_error = failure
    with pytest.raises(SMSDeliveryError):
        manager.invoke("COM11", "send_sms", number="123", text="hello")
    assert first.closed
    assert not manager.snapshot()["devices"][0]["connected"]
    assert first.send_count == 1
    manager.scan()
    assert len(instances) == 2
    assert manager.snapshot()["devices"][0]["connected"]
    assert instances[1].send_count == 0
    manager.close()


def test_modem_rejection_does_not_disconnect_healthy_transport():
    manager, _, instances = setup_manager()
    instances[0].send_error = ATCommandError("AT+CMGS", "+CMS ERROR: 500")
    with pytest.raises(ATCommandError):
        manager.invoke("COM11", "send_sms")
    assert not instances[0].closed
    assert manager.snapshot()["devices"][0]["connected"]
    manager.close()


def test_status_timeout_marks_disconnected_and_releases_port():
    manager, _, instances = setup_manager()
    instances[0].status_error = ATTimeoutError("timed out")
    with pytest.raises(ATTimeoutError):
        manager.status("COM11")
    assert instances[0].closed
    assert not manager.snapshot()["devices"][0]["connected"]


@pytest.mark.parametrize("operation", ["remove", "close"])
def test_remove_and_close_wait_for_inflight_operation(operation):
    manager, ports, instances = setup_manager()
    modem = instances[0]
    with ThreadPoolExecutor(max_workers=2) as executor:
        action = executor.submit(manager.invoke, "COM11", "blocking_operation")
        assert modem.operation_started.wait(1)
        if operation == "remove":
            ports.clear()
            closing = executor.submit(manager.scan)
        else:
            closing = executor.submit(manager.close)
        # Snapshot must remain responsive while teardown waits on one device.
        assert manager.snapshot()["devices"][0]["id"] == "COM11"
        assert not modem.closed
        modem.operation_release.set()
        assert action.result(timeout=1) == "done"
        closing.result(timeout=1)
    assert modem.closed
    if operation == "remove":
        assert manager.snapshot()["devices"] == []


def test_operations_on_other_devices_continue_during_a_blocked_command():
    manager, _, instances = setup_manager([PortInfo("COM11"), PortInfo("COM23")])
    modem = next(modem for modem in instances if modem.port == "COM11")
    with ThreadPoolExecutor(max_workers=2) as executor:
        action = executor.submit(manager.invoke, "COM11", "blocking_operation")
        assert modem.operation_started.wait(1)
        status = executor.submit(manager.status, "COM23")
        assert status.result(timeout=1)["connected"]
        modem.operation_release.set()
        assert action.result(timeout=1) == "done"
    manager.close()


def test_close_continues_after_one_port_fails_and_prevents_resurrection():
    manager, _, instances = setup_manager([PortInfo("COM11"), PortInfo("COM23")])
    instances[0].close_error = True
    manager.close()
    assert all(modem.closed for modem in instances)
    assert all(not device["connected"] for device in manager.snapshot()["devices"])
    manager.scan()
    assert len(instances) == 2
    with pytest.raises(KeyError):
        manager.status("COM11")
    with pytest.raises(KeyError):
        manager.invoke("COM11", "send_sms")


def test_partial_open_failure_is_closed_and_reported():
    class FailingOpen(FakeModem):
        def __enter__(self):
            raise OSError("initialization failed")

    instance = FailingOpen("COM11")
    manager = DeviceManager(discover=lambda: [PortInfo("COM11")], modem_factory=lambda _: instance)
    manager.scan()
    assert instance.closed
    assert manager.snapshot()["devices"][0]["error"] == "initialization failed"
