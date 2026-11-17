"""ESP32 gateway: ``/api/v1/device/*`` (docs/protocolo-esp32.md). HMAC, no JWT.

Every request is authenticated (signature → clock skew → single-use nonce) before the endpoint
runs, and every response — including 4xx/5xx — is signed with ``X-Timestamp``/``X-Signature``
bound to the request nonce. Only when the device is unknown (no secret) is a 401 sent unsigned.
"""

from __future__ import annotations

import logging
import re
import time
from urllib.parse import parse_qsl
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.deps import DbSession
from app.core.config import get_settings
from app.core.errors import DomainError
from app.core.ratelimit import SlidingWindowLimiter
from app.core.security import (
    decrypt_secret,
    device_response_signing_string,
    device_signing_string,
    hmac_sign,
    hmac_verify,
)
from app.db.session import SessionLocal
from app.db.types import utcnow
from app.models import Device, DeviceNonce
from app.models.enums import AccessState, ActorType, DeviceStatus
from app.services import access_engine as engine
from app.services import alerts
from app.services import entrance as entrance_service
from app.services import environment as environment_service
from app.services.context import ActorCtx
from app.ws.hub import defer

log = logging.getLogger(__name__)

_NONCE_RE = re.compile(r"^[0-9a-fA-F]{16,64}$")
MAX_BODY_BYTES = 4096  # protocol limit (docs/protocolo-esp32.md §1)
# Unauthenticated garbage is answered but only audited at this rate per client IP, so a flood
# cannot grow the audit chain or hold the SQLite write lock (the door's own requests come first).
_unauth_audit_limiter = SlidingWindowLimiter(max_events=10, window_s=60)
_CODE_RE = re.compile(r"^[A-Za-z0-9-]{2,30}$")
SESSION_ID = Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")]


@dataclass
class DeviceAuth:
    device_id: int
    secret: str
    nonce: str


class DeviceAuthError(Exception):
    def __init__(self, status: int, code: str, message: str, auth: DeviceAuth | None = None):
        self.status, self.code, self.message, self.auth = status, code, message, auth


def _auth_failed(db: Session, dev: Device | None, reason: str, code_hint: str, cid: str | None,
                 client_ip: str = "?") -> None:
    db.rollback()
    if dev is None and not _unauth_audit_limiter.hit(client_ip):
        return  # anonymous flood: answered, not written
    ctx = ActorCtx(ActorType.DEVICE if dev else ActorType.SYSTEM, dev.id if dev else None, cid)
    ctx.audit(db, "device.auth_failed", "device", dev.id if dev else None,
              {"reason": reason, "device_code": code_hint[:30]})
    alerts.raise_alert(db, ctx, "DEVICE_AUTH_FAIL",
                       f"Petición de dispositivo rechazada ({reason}) para «{code_hint[:30]}»",
                       device_id=dev.id if dev else None, dedupe_s=60)
    db.commit()


def authenticate_device(method: str, path: str, query: str, headers, body: bytes, cid: str | None,
                        client_ip: str = "?") -> DeviceAuth:
    """Signature first (so garbage never reaches the nonce table), then skew, then replay."""
    s = get_settings()
    code = headers.get("x-device-id", "")
    ts = headers.get("x-timestamp", "")
    nonce = headers.get("x-nonce", "")
    sig = headers.get("x-signature", "")
    with SessionLocal() as db:
        if not (_CODE_RE.fullmatch(code) and ts.isdigit() and _NONCE_RE.fullmatch(nonce) and sig):
            _auth_failed(db, None, "MISSING_OR_MALFORMED_HEADERS", code or "?", cid, client_ip)
            raise DeviceAuthError(401, "DEVICE_AUTH_FAILED", "Cabeceras de autenticación ausentes o inválidas")
        dev = db.execute(select(Device).where(Device.device_code == code.upper())).scalar_one_or_none()
        if dev is None:
            _auth_failed(db, None, "UNKNOWN_DEVICE", code, cid, client_ip)
            raise DeviceAuthError(401, "DEVICE_AUTH_FAILED", "Dispositivo desconocido")
        try:
            secret = decrypt_secret(dev.secret_encrypted)
        except ValueError:
            log.error("Cannot decrypt secret of device %s (master key changed?)", dev.device_code)
            _auth_failed(db, dev, "SECRET_UNAVAILABLE", code, cid)
            raise DeviceAuthError(401, "DEVICE_AUTH_FAILED", "Secreto del dispositivo no disponible")
        auth = DeviceAuth(dev.id, secret, nonce.lower())
        keys = [k for k, _ in parse_qsl(query, keep_blank_values=True)]
        if len(keys) != len(set(keys)):  # sorted canonical form would hide the order of duplicates
            _auth_failed(db, dev, "DUPLICATE_QUERY_PARAM", code, cid)
            raise DeviceAuthError(400, "DEVICE_BAD_QUERY", "Parámetros de consulta duplicados", auth)
        if not hmac_verify(secret, device_signing_string(method, path, query, ts, nonce, body), sig):
            _auth_failed(db, dev, "BAD_SIGNATURE", code, cid)
            raise DeviceAuthError(401, "DEVICE_AUTH_FAILED", "Firma inválida", auth)
        if abs(int(time.time()) - int(ts)) > s.device_clock_skew_s:
            _auth_failed(db, dev, "CLOCK_SKEW", code, cid)
            raise DeviceAuthError(401, "DEVICE_CLOCK_SKEW", "Marca de tiempo fuera de la ventana permitida", auth)
        db.add(DeviceNonce(device_id=dev.id, nonce=auth.nonce, seen_at=utcnow()))
        try:
            db.flush()
        except IntegrityError:
            _auth_failed(db, dev, "REPLAY", code, cid)
            raise DeviceAuthError(401, "DEVICE_REPLAY", "Nonce repetido (posible reenvío)", auth)
        dev.last_seen_at = utcnow()
        if dev.status == DeviceStatus.OFFLINE:
            dev.status = DeviceStatus.ONLINE
            ActorCtx(ActorType.DEVICE, dev.id, cid).audit(db, "device.online", "device", dev.id)
            defer(db, "device.status", engine.device_status_dict(dev))
        db.commit()
        return auth


def _envelope(status: int, code: str, message: str, cid: str | None, **extra) -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"error": {"code": code, "message": message, "correlation_id": cid, **extra}})


def _sign(response: Response, method: str, path: str, auth: DeviceAuth | None) -> Response:
    if auth is None:
        return response
    ts = str(int(time.time()))
    msg = device_response_signing_string(method, path, auth.nonce, response.status_code, ts, bytes(response.body))
    response.headers["X-Timestamp"] = ts
    response.headers["X-Signature"] = hmac_sign(auth.secret, msg)
    return response


class SignedDeviceRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            cid = getattr(request.state, "correlation_id", None)
            method, path = request.method, request.url.path
            declared = request.headers.get("content-length")
            if declared is not None and (not declared.isdigit() or int(declared) > MAX_BODY_BYTES):
                return _envelope(413, "PAYLOAD_TOO_LARGE", "Cuerpo demasiado grande", cid)
            body = b""
            async for chunk in request.stream():  # also caps chunked bodies without Content-Length
                body += chunk
                if len(body) > MAX_BODY_BYTES:
                    return _envelope(413, "PAYLOAD_TOO_LARGE", "Cuerpo demasiado grande", cid)
            request._body = body  # let FastAPI parse the JSON body we already consumed
            client_ip = request.client.host if request.client else "?"
            try:
                auth = await run_in_threadpool(authenticate_device, method, path, request.url.query,
                                               request.headers, body, cid, client_ip)
            except DeviceAuthError as e:
                return _sign(_envelope(e.status, e.code, e.message, cid), method, path, e.auth)
            request.state.device_auth = auth
            try:
                response = await original(request)
            except DomainError as e:
                response = _envelope(e.status, e.code, e.message, cid)
            except RequestValidationError as e:
                response = _envelope(422, "VALIDATION_ERROR", "Datos de entrada inválidos", cid,
                                     details=[{"loc": list(x["loc"]), "msg": x["msg"]} for x in e.errors()])
            except StarletteHTTPException as e:
                response = _envelope(e.status_code, "HTTP_ERROR", str(e.detail), cid)
            except Exception:  # noqa: BLE001 — fail-closed, but still a signed answer
                log.exception("Device endpoint failed (correlation_id=%s)", cid)
                response = _envelope(500, "INTERNAL_ERROR", "Error interno del servidor", cid)
            return _sign(response, method, path, auth)

        return handler


router = APIRouter(prefix="/device", tags=["device gateway (ESP32, HMAC)"], route_class=SignedDeviceRoute)


def current_device(request: Request, db: DbSession) -> Device:
    dev = db.get(Device, request.state.device_auth.device_id, populate_existing=True)
    if dev is None:  # deleted between auth and handler
        raise DomainError("DEVICE_AUTH_FAILED", "Dispositivo desconocido", 401)
    return dev


CurrentDevice = Annotated[Device, Depends(current_device)]


def _ctx(request: Request, dev: Device) -> ActorCtx:
    return engine.device_ctx(dev, getattr(request.state, "correlation_id", None))


# ------------------------------------------------------------------ schemas
class _Loose(BaseModel):
    model_config = ConfigDict(extra="ignore")


class SensorsIn(_Loose):
    rfid: str | None = Field(default=None, max_length=12)
    ultrasonic: str | None = Field(default=None, max_length=12)
    dht: str | None = Field(default=None, max_length=12)


class HeartbeatIn(_Loose):
    fw: str | None = Field(default=None, max_length=20)
    state: str | None = Field(default=None, max_length=24)
    door: str | None = Field(default=None, max_length=12)
    present: bool | None = None
    distance_cm: float | None = None
    rssi: int | None = None
    uptime_s: int | None = None
    free_heap: int | None = None
    session_id: str | None = Field(default=None, max_length=32)
    sensors: SensorsIn | None = None


class PresenceIn(_Loose):
    present: bool
    distance_cm: float | None = None
    threshold_cm: float | None = None


class StartIn(_Loose):
    uid: str = Field(min_length=1, max_length=40)
    distance_cm: float | None = None
    fw: str | None = Field(default=None, max_length=20)


class OpenedIn(_Loose):
    open_ms: int | None = Field(default=None, ge=0, le=60000)


class ClosedIn(_Loose):
    reason: Literal["TIMER", "EMERGENCY", "LOCAL_BUTTON"] = "TIMER"


class EventIn(_Loose):
    type: str = Field(min_length=1, max_length=40, pattern=r"^[A-Z0-9_]+$")
    detail: str | None = Field(default=None, max_length=300)


# ------------------------------------------------------------------ endpoints
@router.post("/heartbeat")
def heartbeat(body: HeartbeatIn, request: Request, dev: CurrentDevice, db: DbSession):
    """Liveness + telemetry. Returns config and, at most once, ``EMERGENCY_CLOSE``."""
    data = body.model_dump()
    data["sensors"] = body.sensors.model_dump(exclude_none=True) if body.sensors else {}
    out = engine.heartbeat(db, _ctx(request, dev), dev, data)
    db.commit()
    return out


@router.post("/presence")
def presence(body: PresenceIn, request: Request, dev: CurrentDevice, db: DbSession):
    out = engine.presence(db, _ctx(request, dev), dev, body.present, body.distance_cm)
    db.commit()
    return out


@router.post("/access/start")
def access_start(body: StartIn, request: Request, dev: CurrentDevice, db: DbSession):
    """Card read (with distance). Immediate denials come back without ``session_id``."""
    s = get_settings()
    sess = engine.start(db, _ctx(request, dev), dev, body.uid, body.distance_cm)
    db.commit()
    if sess.state == AccessState.DENIED:
        return {"state": "DENIED", "reason_code": sess.reason_code}
    return {"session_id": sess.id, "state": str(sess.state), "poll_ms": s.access_poll_ms,
            "timeout_s": s.access_session_timeout_s}


class ExitButtonIn(_Loose):
    source: Literal["BUTTON"] = "BUTTON"


@router.post("/exit-button")
def exit_button(body: ExitButtonIn, request: Request, dev: CurrentDevice, db: DbSession):
    """Inside exit button. Opens only if someone is inside this door (backend knowledge);
    otherwise ``{state: DENIED, reason_code: NOBODY_INSIDE}``. Same polling flow as a card."""
    s = get_settings()
    sess = engine.exit_button(db, _ctx(request, dev), dev)
    db.commit()
    if sess.state == AccessState.DENIED:
        return {"state": "DENIED", "reason_code": sess.reason_code}
    return {"session_id": sess.id, "state": str(sess.state), "poll_ms": s.access_poll_ms,
            "timeout_s": s.access_session_timeout_s}


@router.get("/access/{session_id}")
def access_poll(session_id: SESSION_ID, request: Request, dev: CurrentDevice, db: DbSession,
                distance_cm: Annotated[float | None, Query()] = None):
    sess = engine.poll(db, _ctx(request, dev), dev, session_id, distance_cm)
    db.commit()
    out: dict = {"session_id": sess.id, "state": str(sess.state)}
    if sess.reason_code:
        out["reason_code"] = sess.reason_code
    if sess.state == AccessState.GRANTED:
        out["open_ms"] = dev.door_open_ms
        # For the door LCD ("Bienvenido" + name). Only on GRANTED, inside the signed response.
        out["greeting"], out["display_name"] = engine.lcd_greeting(db, sess)
    return out


@router.post("/access/{session_id}/opened")
def access_opened(session_id: SESSION_ID, body: OpenedIn, request: Request, dev: CurrentDevice, db: DbSession):
    engine.confirm_opened(db, _ctx(request, dev), dev, session_id, body.open_ms)
    db.commit()
    return {"ok": True}


@router.post("/access/{session_id}/closed")
def access_closed(session_id: SESSION_ID, body: ClosedIn, request: Request, dev: CurrentDevice, db: DbSession):
    engine.confirm_closed(db, _ctx(request, dev), dev, session_id, body.reason)
    db.commit()
    return {"ok": True}


@router.post("/event")
def device_event(body: EventIn, request: Request, dev: CurrentDevice, db: DbSession):
    engine.device_event(db, _ctx(request, dev), dev, body.type, body.detail)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ main entrance (QR → LED)
class EntrancePollIn(_Loose):
    pass


class EntranceAckIn(_Loose):
    shown: bool = True


@router.post("/entrance/poll")
def entrance_poll(body: EntrancePollIn, request: Request, dev: CurrentDevice, db: DbSession):
    """Next LED signal of the main entrance, delivered **once**: ``{signal: null}`` or
    ``{signal: {id, result, led_ms, display_name}}``. Signals not polled within 10 s expire."""
    signal = entrance_service.poll_signal(db, _ctx(request, dev), dev)
    db.commit()
    return {"signal": signal}


@router.post("/entrance/{signal_id}/ack")
def entrance_ack(signal_id: SESSION_ID, body: EntranceAckIn, request: Request, dev: CurrentDevice, db: DbSession):
    entrance_service.ack_signal(db, _ctx(request, dev), dev, signal_id, body.shown)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ DHT11
class EnvironmentIn(_Loose):
    temperature_c: float | None = Field(default=None, ge=-40, le=125, allow_inf_nan=False)
    humidity_pct: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    sensor: Literal["OK", "ERROR"] = "OK"


@router.post("/environment")
def environment(body: EnvironmentIn, request: Request, dev: CurrentDevice, db: DbSession):
    """Server-room reading every 10 s. Reply ``{ok, fan, alarm}`` (fan with 1 °C hysteresis).
    ``sensor:"OK"`` without both values is treated as ``ERROR`` (fail-safe)."""
    out = environment_service.record(db, _ctx(request, dev), dev, body.temperature_c, body.humidity_pct, body.sensor)
    db.commit()
    return out
