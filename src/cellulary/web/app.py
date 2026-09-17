"""Loopback-only HTTP API. Serial work runs in worker threads, never the event loop."""
from __future__ import annotations

import asyncio
import hmac
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from cellulary.errors import CellularyError, SMSDeliveryError
from cellulary.manager import DeviceManager
from cellulary.network import HostNetwork


class SmsRequest(BaseModel):
    number: str = Field(min_length=1, max_length=32, pattern=r"^\+?[0-9]+$")
    text: str = Field(min_length=1, max_length=2000)


class NumberRequest(BaseModel):
    number: str = Field(min_length=1, max_length=32, pattern=r"^\+?[0-9]+$")


class ContextRequest(BaseModel):
    cid: int = Field(default=1, ge=1, le=16)


class ApnRequest(ContextRequest):
    apn: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9.-]+$")


class HostRequest(BaseModel):
    interface: str = Field(min_length=1, max_length=128)
    profile: str = Field(default="", max_length=128)


def create_app(manager=None, *, poll_interval=20, autostart=True, network=None):
    manager = manager or DeviceManager()
    network = network or HostNetwork()
    token = secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(app):
        stop = asyncio.Event()

        async def poll():
            while not stop.is_set():
                try:
                    await asyncio.to_thread(manager.scan)
                except Exception as exc:
                    manager.event(f"扫描失败: {exc}", level="error")
                try:
                    await asyncio.wait_for(stop.wait(), timeout=poll_interval)
                except TimeoutError:
                    pass

        task = asyncio.create_task(poll()) if autostart else None
        try:
            yield
        finally:
            stop.set()
            try:
                if task:
                    await task
            finally:
                await asyncio.to_thread(manager.close)

    app = FastAPI(title="Cellulary", version="0.1.0", lifespan=lifespan)
    app.state.manager = manager
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"])

    @app.middleware("http")
    async def protect(request: Request, call_next):
        origin = request.headers.get("origin")
        origin_url = urlparse(origin) if origin else None
        if origin_url and (origin_url.netloc != request.headers.get("host") or origin_url.scheme != request.url.scheme):
            return JSONResponse({"detail": "拒绝跨站请求"}, status_code=403)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            supplied_token = request.headers.get("x-cellulary-token", "")
            if not supplied_token.isascii() or not hmac.compare_digest(supplied_token, token):
                return JSONResponse({"detail": "会话已过期，请刷新页面"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        if not request.url.path.startswith("/docs"):
            response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse({"detail": "模块未连接，请重新扫描"}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(SMSDeliveryError)
    async def sms_failed(request, exc):
        return JSONResponse({"detail": str(exc), "submitted_references": exc.references,
                             "total_segments": exc.total_segments, "retry_safe": False}, status_code=502)

    @app.exception_handler(CellularyError)
    async def modem_failed(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=502)

    @app.exception_handler(Exception)
    async def failed(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=502)

    @app.get("/api/session")
    def session():
        return {"token": token, "version": "0.1.0", "mode": "demo" if manager.demo else "hardware"}

    @app.get("/api/devices")
    def devices():
        return manager.snapshot()

    @app.post("/api/discover")
    def discover():
        return manager.scan()

    @app.get("/api/events")
    def events():
        return manager.events()

    @app.get("/api/devices/{device_id}/status")
    def status(device_id: str):
        return manager.status(device_id)

    @app.get("/api/devices/{device_id}/sms")
    def sms_list(device_id: str):
        return {"messages": manager.invoke(device_id, "list_sms")}

    @app.post("/api/devices/{device_id}/sms")
    def sms_send(device_id: str, request: SmsRequest):
        return manager.invoke(device_id, "send_sms", number=request.number, text=request.text)

    @app.get("/api/devices/{device_id}/data")
    def data_status(device_id: str):
        return manager.invoke(device_id, "data_status")

    @app.post("/api/devices/{device_id}/data/configure")
    def configure(device_id: str, request: ApnRequest):
        result = manager.invoke(device_id, "configure_apn", apn=request.apn, context_id=request.cid)
        return result or {"message": "APN 已配置"}

    @app.post("/api/devices/{device_id}/data/activate")
    def activate(device_id: str, request: ContextRequest):
        result = manager.invoke(device_id, "activate_data", context_id=request.cid)
        return result or {"message": "PDP 已激活；请检查主机网卡与路由"}

    @app.post("/api/devices/{device_id}/data/deactivate")
    def deactivate(device_id: str, request: ContextRequest):
        result = manager.invoke(device_id, "deactivate_data", context_id=request.cid)
        return result or {"message": "PDP 已停用"}

    @app.get("/api/devices/{device_id}/calls")
    def calls(device_id: str):
        return {"calls": manager.invoke(device_id, "list_calls")}

    @app.get("/api/devices/{device_id}/data/usb")
    def usb_data(device_id: str):
        return manager.invoke(device_id, "usb_data_status")

    @app.post("/api/devices/{device_id}/data/usb/connect")
    def usb_connect(device_id: str, request: ContextRequest):
        return manager.invoke(device_id, "connect_usb_data", context_id=request.cid)

    @app.post("/api/devices/{device_id}/data/usb/disconnect")
    def usb_disconnect(device_id: str, request: ContextRequest):
        return manager.invoke(device_id, "disconnect_usb_data", context_id=request.cid)

    @app.post("/api/devices/{device_id}/calls/dial")
    def dial(device_id: str, request: NumberRequest):
        return manager.invoke(device_id, "dial", number=request.number) or {"message": "已请求拨号"}

    @app.post("/api/devices/{device_id}/calls/answer")
    def answer(device_id: str):
        return manager.invoke(device_id, "answer") or {"message": "已请求接听"}

    @app.post("/api/devices/{device_id}/calls/hangup")
    def hangup(device_id: str):
        return manager.invoke(device_id, "hangup") or {"message": "已请求挂断"}

    @app.get("/api/host/network")
    def host_status():
        return network.status()

    @app.post("/api/host/network/connect")
    def host_connect(request: HostRequest):
        return network.connect(request.interface, request.profile)

    @app.post("/api/host/network/disconnect")
    def host_disconnect(request: HostRequest):
        return network.disconnect(request.interface)

    app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="console")
    return app
