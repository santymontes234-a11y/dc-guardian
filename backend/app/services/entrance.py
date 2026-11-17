"""Main entrance (ENTRADA_PRINCIPAL): QR scan decision and the one-shot LED signal
(docs/contrato-qr-dht11.md §2–§3). Fail-closed: the first failed check denies.

    kiosk ── POST /kiosk/entrance/scan {qr_text} ──► scan() ──► EntranceEvent (bitácora)
                                                               └─► signal PENDIENTE
    ESP32 ── POST /device/entrance/poll ──► poll_signal() → ENTREGADA (only once)
    ESP32 ── POST /device/entrance/{id}/ack ──► ack_signal() → MOSTRADA
    not polled within DCG_ENTRANCE_SIGNAL_TTL_S (10 s) ──► EXPIRADA (discarded)

The QR only identifies the engineer (Registro 1 material). The decision also requires an
APROBADA authorization in force **now** (Registro 2), checked with the same function and
reason codes as the RFID door. The green LED is independent of the server-room servo.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import DomainError, not_found
from app.core.ratelimit import SlidingWindowLimiter
from app.models import Area, Device, Engineer, EntranceEvent, QrCredential
from app.models.enums import DeviceStatus, EngineerStatus, EntranceSignalStatus, QrStatus
from app.services import access_engine as engine
from app.services import alerts
from app.services import qr as qr_service
from app.services.context import ActorCtx
from app.ws.hub import defer

SIG = EntranceSignalStatus
GRANTED, DENIED = "GRANTED", "DENIED"
METHOD_QR = "QR"

# QR-specific denials → (alert type, dedupe seconds). Registro 2 / engineer denials reuse the
# access engine mapping; DEVICE_OFFLINE already has its own DEVICE_OFFLINE alert.
_QR_ALERTS: dict[str, tuple[str, int | None]] = {
    "QR_INVALID": ("UNKNOWN_QR", 60),
    "QR_UNKNOWN": ("UNKNOWN_QR", 60),
    "QR_REVOKED": ("QR_BLOCKED", None),
    "QR_EXPIRED": ("QR_BLOCKED", None),
}

_limiter: SlidingWindowLimiter | None = None


def scan_limiter() -> SlidingWindowLimiter:
    global _limiter
    per_min = get_settings().qr_scan_rate_per_minute
    if _limiter is None or _limiter.max_events != per_min:
        _limiter = SlidingWindowLimiter(max_events=per_min, window_s=60)
    return _limiter


def entrance_area(db: Session) -> Area | None:
    return db.execute(select(Area).where(Area.code == get_settings().entrance_area_code)).scalar_one_or_none()


def entrance_device(db: Session) -> Device | None:
    return db.execute(
        select(Device).where(Device.device_code == get_settings().entrance_device_code)
    ).scalar_one_or_none()


def device_online(dev: Device | None, now) -> bool:
    """ONLINE *and* a recent heartbeat: the sweep may not have marked a silent device yet."""
    if dev is None or dev.status != DeviceStatus.ONLINE or dev.last_seen_at is None:
        return False
    return dev.last_seen_at >= now - timedelta(seconds=get_settings().device_offline_s)


def _decide(db: Session, now, qr_text: str, dev: Device | None
            ) -> tuple[str | None, QrCredential | None, Engineer | None, int | None]:
    """(reason_code or None, credential, engineer, request_id) — checks in the contract order."""
    token = qr_service.parse(qr_text)
    if token is None:
        return "QR_INVALID", None, None, None
    cred = qr_service.find_by_token(db, token)
    if cred is None:
        return "QR_UNKNOWN", None, None, None
    eng = db.get(Engineer, cred.engineer_id)
    if cred.status != QrStatus.ACTIVE:
        return "QR_REVOKED", cred, eng, None
    if cred.expires_at is not None and cred.expires_at <= now:
        return "QR_EXPIRED", cred, eng, None
    if eng is None or eng.status != EngineerStatus.ACTIVE:
        return "ENGINEER_INACTIVE", cred, eng, None
    # Registro 2: any area of the center (all of them lie behind the main entrance).
    req, reason = engine.authorization_for_engineer(db, eng.id, None, now)
    if req is None:
        return reason or "NO_VALID_AUTH", cred, eng, None
    if not device_online(dev, now):
        return "DEVICE_OFFLINE", cred, eng, req.id
    return None, cred, eng, req.id


def scan(db: Session, ctx: ActorCtx, qr_text: str, client_key: str) -> dict:
    """Kiosk scan. Every scan (granted or denied) is logged, audited, pushed by WebSocket and
    queues one signal for the entrance device. ``429`` above the per-client rate."""
    if not scan_limiter().hit(client_key):
        raise DomainError("RATE_LIMITED", "Demasiados escaneos; espera un minuto", 429, {"Retry-After": "60"})
    s = get_settings()
    now = ctx.now
    area, dev = entrance_area(db), entrance_device(db)
    reason, cred, eng, request_id = _decide(db, now, qr_text, dev)
    ev = EntranceEvent(
        area_id=area.id if area else None, device_id=dev.id if dev else None,
        engineer_id=eng.id if eng else None, qr_credential_id=cred.id if cred else None,
        request_id=request_id if reason is None else None, method=METHOD_QR,
        result=GRANTED if reason is None else DENIED, reason_code=reason, created_at=now,
        signal_status=SIG.PENDING if dev is not None else SIG.NONE,
    )
    db.add(ev)
    db.flush()
    details = {"result": ev.result, "reason_code": reason, "engineer_id": ev.engineer_id,
               "qr_prefix": cred.prefix if cred else None, "request_id": ev.request_id,
               "area": s.entrance_area_code, "method": METHOD_QR, "signal": str(ev.signal_status)}
    ctx.audit(db, "entrance.qr_granted" if reason is None else "entrance.qr_denied", "entrance_event", ev.id, details)
    if reason is None:
        cred.last_used_at = now
    else:
        _alert(db, ctx, ev, reason, cred)
    defer(db, "entrance.scan", event_row(db, ev, area=area, device=dev, engineer=eng))
    db.commit()

    out: dict = {"result": ev.result, "area": s.entrance_area_code, "event_id": ev.id}
    if reason is not None:
        out["reason_code"] = reason
        out["reason"] = engine.reason_text(reason)
    elif eng is not None:  # identity is shown only on success (a found QR must not reveal its owner)
        out["display_name"] = eng.full_name
        out["position"] = eng.position
    return out


def _alert(db: Session, ctx: ActorCtx, ev: EntranceEvent, reason: str, cred: QrCredential | None) -> None:
    msg = f"QR denegado en la entrada principal: {engine.reason_text(reason)}"
    if reason in _QR_ALERTS:
        type_, dedupe = _QR_ALERTS[reason]
        alerts.raise_alert(db, ctx, type_, msg + (f" (QR {cred.prefix}…)" if cred else ""),
                           engineer_id=ev.engineer_id, dedupe_s=dedupe)
        return
    mapped = engine.denial_alert(reason)
    if mapped is not None:
        type_, sev = mapped
        alerts.raise_alert(db, ctx, type_, msg, severity=sev, device_id=ev.device_id, engineer_id=ev.engineer_id)


# ------------------------------------------------------------------ signals for the device
def expire_signals(db: Session, ctx: ActorCtx, device_id: int | None = None) -> int:
    """PENDIENTE signals older than the TTL become EXPIRADA (never delivered afterwards)."""
    cutoff = ctx.now - timedelta(seconds=get_settings().entrance_signal_ttl_s)
    stmt = select(EntranceEvent).where(EntranceEvent.signal_status == SIG.PENDING,
                                       EntranceEvent.created_at <= cutoff)
    if device_id is not None:
        stmt = stmt.where(EntranceEvent.device_id == device_id)
    n = 0
    for ev in db.execute(stmt).scalars():
        ev.signal_status = SIG.EXPIRED
        ctx.audit(db, "entrance.signal_expired", "entrance_event", ev.id, {"result": ev.result})
        n += 1
    return n


def poll_signal(db: Session, ctx: ActorCtx, dev: Device) -> dict | None:
    """Oldest pending, non-expired signal for this device, delivered exactly once."""
    s = get_settings()
    expire_signals(db, ctx, dev.id)
    ev = db.execute(
        select(EntranceEvent).where(EntranceEvent.device_id == dev.id, EntranceEvent.signal_status == SIG.PENDING)
        .order_by(EntranceEvent.created_at, EntranceEvent.id).limit(1)
    ).scalar_one_or_none()
    if ev is None:
        return None
    ev.signal_status = SIG.DELIVERED
    ev.delivered_at = ctx.now
    ctx.audit(db, "entrance.signal_delivered", "entrance_event", ev.id, {"result": ev.result})
    name = ""
    if ev.result == GRANTED and ev.engineer_id is not None:
        eng = db.get(Engineer, ev.engineer_id)
        name = engine.ascii_text(eng.full_name, 40) if eng else ""
    return {"id": ev.id, "result": ev.result, "led_ms": s.entrance_led_ms, "display_name": name}


def ack_signal(db: Session, ctx: ActorCtx, dev: Device, signal_id: str, shown: bool) -> None:
    ev = db.get(EntranceEvent, signal_id, populate_existing=True)
    if ev is None or ev.device_id != dev.id:
        raise not_found("SIGNAL_NOT_FOUND", "Señal de entrada no encontrada")
    if ev.signal_status == SIG.SHOWN:
        return  # idempotent retry
    if ev.signal_status != SIG.DELIVERED:
        raise DomainError("SIGNAL_NOT_DELIVERED", "La señal no fue entregada al dispositivo", 409)
    ev.acked_at = ctx.now
    if shown:
        ev.signal_status = SIG.SHOWN
    ctx.audit(db, "entrance.signal_shown" if shown else "entrance.signal_not_shown", "entrance_event", ev.id,
              {"result": ev.result})


# ------------------------------------------------------------------ serialization
def event_row(db: Session, ev: EntranceEvent, *, area: Area | None = None, device: Device | None = None,
              engineer: Engineer | None = None) -> dict:
    """Bitácora row (same shape as ``services.access_log``)."""
    from app.services import access_log

    return access_log.entrance_row(db, ev, area=area, device=device, engineer=engineer)
