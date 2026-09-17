from fastapi.testclient import TestClient

from cellulary.errors import SMSDeliveryError
from cellulary.web.app import create_app


class Manager:
    demo = False

    def __init__(self):
        self.actions = []

    def snapshot(self):
        return {"devices": [], "scanning": False}

    def scan(self):
        self.actions.append("scan")
        return self.snapshot()

    def status(self, device_id):
        raise KeyError(device_id)

    def invoke(self, device_id, method, **kwargs):
        self.actions.append((device_id, method, kwargs))
        return {"status": "submitted"}

    def events(self):
        return {"events": []}

    def close(self):
        pass


def test_reads_never_start_a_billable_operation():
    manager = Manager()
    with TestClient(create_app(manager, autostart=False)) as client:
        assert client.get("/api/devices").json()["devices"] == []
        assert client.get("/api/devices/missing/status").status_code == 404
        assert manager.actions == []


def test_gnss_reads_and_mutations_use_separate_routes_and_token():
    manager = Manager()
    with TestClient(create_app(manager, autostart=False)) as client:
        assert client.get("/api/devices/COM11/gnss").status_code == 200
        assert client.get("/api/devices/COM11/gnss/location").status_code == 200
        assert client.post("/api/devices/COM11/gnss/start").status_code == 403
        assert [action[1] for action in manager.actions] == ["gnss_status", "gnss_location"]
        headers = {"X-Cellulary-Token": client.get("/api/session").json()["token"]}
        assert client.post("/api/devices/COM11/gnss/start", headers=headers).status_code == 200
        assert client.post("/api/devices/COM11/gnss/stop", headers=headers).status_code == 200
        assert [action[1] for action in manager.actions][-2:] == ["start_gnss", "stop_gnss"]


def test_per_device_network_status_filters_to_known_device():
    class Device(Manager):
        def snapshot(self):
            return {"devices": [{"id": "COM11"}]}

    class Network:
        def device_status(self, port):
            return {"device_port": port, "adapters": []}

    with TestClient(create_app(Device(), autostart=False, network=Network())) as client:
        assert client.get("/api/devices/COM11/network").json()["device_port"] == "COM11"
        assert client.get("/api/devices/missing/network").status_code == 404


def test_cross_site_requests_and_missing_token_cannot_send_sms():
    manager = Manager()
    with TestClient(create_app(manager, autostart=False)) as client:
        payload = {"number": "+441234567890", "text": "hello"}
        assert client.post("/api/devices/COM11/sms", json=payload).status_code == 403
        token = client.get("/api/session").json()["token"]
        assert client.post("/api/devices/COM11/sms", json=payload,
                           headers={"X-Cellulary-Token": token, "Origin": "https://evil.example"}).status_code == 403
        assert client.get("/api/session", headers={"Host": "evil.example"}).status_code == 400
        assert client.post("/api/devices/COM11/sms", json=payload,
                           headers={"X-Cellulary-Token": token, "Origin": "https://testserver"}).status_code == 403
        assert client.post("/api/discover", headers=[(b"X-Cellulary-Token", b"\xe9")]).status_code == 403
        assert manager.actions == []
        assert client.post("/api/devices/COM11/sms", json=payload,
                           headers={"X-Cellulary-Token": token}).status_code == 200
        assert manager.actions == [("COM11", "send_sms", payload)]


def test_number_and_apn_injection_rejected_before_hardware():
    manager = Manager()
    with TestClient(create_app(manager, autostart=False)) as client:
        headers = {"X-Cellulary-Token": client.get("/api/session").json()["token"]}
        assert client.post("/api/devices/COM11/calls/dial", json={"number": "123;ATH"}, headers=headers).status_code == 422
        assert client.post("/api/devices/COM11/data/configure", json={"apn": 'internet"\rATD123;'}, headers=headers).status_code == 422
        assert client.post("/api/devices/COM11/data/activate", json={"cid": 0}, headers=headers).status_code == 422
        assert manager.actions == []


def test_partial_sms_error_preserves_submission_evidence():
    class PartialManager(Manager):
        def invoke(self, *args, **kwargs):
            raise SMSDeliveryError("第二段超时，勿自动重发", [7], 2)

    with TestClient(create_app(PartialManager(), autostart=False)) as client:
        headers = {"X-Cellulary-Token": client.get("/api/session").json()["token"]}
        response = client.post("/api/devices/COM11/sms", json={"number": "+441234567890", "text": "test"}, headers=headers)
        assert response.status_code == 502
        assert response.json()["submitted_references"] == [7]
        assert response.json()["retry_safe"] is False


def test_shutdown_always_releases_devices_on_lifespan_failure():
    import asyncio

    import pytest

    manager = Manager()
    closed = []
    manager.close = lambda: closed.append(True)
    app = create_app(manager, autostart=False)

    async def run():
        with pytest.raises(RuntimeError, match="aborted"):
            async with app.router.lifespan_context(app):
                raise RuntimeError("aborted")

    asyncio.run(run())
    assert closed == [True]
