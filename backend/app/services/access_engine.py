"""Multi-factor access engine (design doc §2.3–2.4). Fail-closed: any doubt → door stays shut.

Entry (ENTRADA):

    card read ─► checks ─► AWAITING_FACE ─(kiosk 1:1 OK)─► FACE_OK ─(poll: presence + still in
    force)─► GRANTED ─► OPENED ─► CLOSED            any failure ─► DENIED / TIMEOUT

Exit (SALIDA): a second card pass by an engineer who is inside (last completed session at this
door was an ENTRADA within ``exit_window_hours``) needs the same 1:1 face match but **no
authorization**, so nobody is locked inside after their authorization ends, is suspended or
has the card temporarily locked (those cases raise a CRITICAL alert). The face is required
because there is a single reader: without it a cloned or lent card would open the door from
outside (security review F8, A1). The card must still be ACTIVA and linked to that engineer.

The only authorization source is Registro 2: ``services.requests.find_in_force`` (checked at
card read, again after the face match, and again right before GRANTED). Registro 1 (engineer
record, face samples) never grants anything on its own.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.errors import DomainError, not_found
from app.models import AccessSession, AuthorizationRequest, Device, Engineer, RfidCard, normalize_uid
from app.models.enums import (
    AccessDirection,
    AccessState,
    ActorType,
    AlertSeverity,
    CardStatus,
    DeviceStatus,
    EngineerStatus,
    RequestStatus,
)
from app.services import alerts
from app.services import requests as requests_service
from app.services.context import ActorCtx
from app.ws.hub import defer

log = logging.getLogger(__name__)

ST = AccessState
PENDING_STATES = frozenset({ST.CARD_READ, ST.AWAITING_FACE, ST.FACE_OK})
TERMINAL_STATES = frozenset({ST.CLOSED, ST.DENIED, ST.TIMEOUT})

REASON_TEXT: dict[str, str] = {
    "UNKNOWN_CARD": "Tarjeta no registrada en el sistema",
    "CARD_NOT_ACTIVE": "La tarjeta no está activa (bloqueada, perdida o dada de baja)",
    "CARD_LOCKED": "Tarjeta bloqueada temporalmente por intentos fallidos",
    "CARD_NOT_LINKED": "La tarjeta no está vinculada a ningún ingeniero",
    "ENGINEER_INACTIVE": "El ingeniero no está activo (inactivo, suspendido o eliminado)",
    "NO_VALID_AUTH": "No existe ninguna autorización para esta tarjeta en esta área",
    "REQUEST_PENDING": "La solicitud de autorización aún no ha sido aprobada",
    "AUTH_EXPIRED": "La autorización ha vencido",
    "AUTH_REVOKED": "La autorización fue revocada",
    "AUTH_NOT_STARTED": "La ventana de la autorización aún no ha comenzado",
    "AUTH_REJECTED": "La solicitud de autorización fue rechazada",
    "NO_FACE_ENROLLED": "El ingeniero no tiene rostro registrado",
    "FACE_MISMATCH": "El rostro no coincide con el titular de la tarjeta",
    "LIVENESS_FAILED": "Prueba de vida fallida (imágenes estáticas o idénticas)",
    "FACE_NOT_DETECTED": "No se detectó un rostro en la cámara",
    "MULTIPLE_FACES": "Hay más de un rostro frente a la cámara",
    "MODEL_MISMATCH": "Las muestras faciales se registraron con otro modelo",
    "BIOMETRIC_ERROR": "Error en la verificación facial",
    "BAD_FRAME_COUNT": "Número de capturas incorrecto",
    "PRESENCE_LOST": "La persona se alejó de la puerta antes de la decisión",
    "SENSOR_ERROR": "Lectura del sensor de presencia no válida",
    "DEVICE_DISABLED": "Dispositivo deshabilitado por un administrador",
    "TIMEOUT": "Tiempo de verificación agotado",
    "SESSION_SUPERSEDED": "Se inició otro intento en la misma puerta",
    "NOBODY_INSIDE": "Botón de salida pulsado sin nadie dentro: la puerta no se abre",
    # Main entrance (QR, docs/contrato-qr-dht11.md §2)
    "QR_INVALID": "El código QR no tiene un formato válido",
    "QR_UNKNOWN": "El código QR no está registrado",
    "QR_REVOKED": "El código QR fue revocado",
    "QR_EXPIRED": "El código QR ha vencido",
    "QR_USED": "El pase de un solo uso ya fue utilizado",
    "DEVICE_OFFLINE": "El dispositivo de la entrada no está en línea",
}

# reason → (alert type, severity override). Missing → no alert.
_ALERT_FOR: dict[str, tuple[str, AlertSeverity | None]] = {
    "UNKNOWN_CARD": ("UNKNOWN_CARD", None),
    "CARD_NOT_ACTIVE": ("CARD_BLOCKED", None),
    "CARD_LOCKED": ("CARD_BLOCKED", None),
    "CARD_NOT_LINKED": ("CARD_NOT_LINKED", None),
    "ENGINEER_INACTIVE": ("INACTIVE_ENGINEER", None),
    "NO_VALID_AUTH": ("NO_VALID_AUTH", None),
    "REQUEST_PENDING": ("NO_VALID_AUTH", AlertSeverity.INFO),
    "AUTH_EXPIRED": ("NO_VALID_AUTH", None),
    "AUTH_REVOKED": ("NO_VALID_AUTH", None),
    "AUTH_NOT_STARTED": ("NO_VALID_AUTH", AlertSeverity.INFO),
    "AUTH_REJECTED": ("NO_VALID_AUTH", None),
    "NO_FACE_ENROLLED": ("NO_FACE_ENROLLED", None),
    "FACE_MISMATCH": ("FACE_MISMATCH", None),
    "LIVENESS_FAILED": ("FACE_MISMATCH", None),
    "PRESENCE_LOST": ("PRESENCE_LOST", None),
    "SENSOR_ERROR": ("SENSOR_FAULT", None),
    "DEVICE_DISABLED": ("DEVICE_DISABLED", None),
}

# Denials that count towards REPEATED_FAILURES for the card (not sensor glitches or walking away).
_COUNTS_AS_FAILURE = frozenset({
    "CARD_NOT_LINKED", "ENGINEER_INACTIVE", "NO_VALID_AUTH", "REQUEST_PENDING", "AUTH_EXPIRED",
    "AUTH_REVOKED", "AUTH_NOT_STARTED", "AUTH_REJECTED", "NO_FACE_ENROLLED", "FACE_MISMATCH",
    "LIVENESS_FAILED",
})

# Biometric results that let the person try again within the same session.
RETRYABLE_FACE = frozenset({"FACE_NOT_DETECTED", "MULTIPLE_FACES", "NO_FRAMES", "BAD_FRAME_COUNT"})


def denial_alert(reason: str) -> tuple[str, AlertSeverity | None] | None:
    """(alert type, severity override) raised for a denial reason, or None."""
    return _ALERT_FOR.get(reason)


def reason_text(code: str | None) -> str | None:
    return None if code is None else REASON_TEXT.get(code, code)


# ------------------------------------------------------------------ serialization
def session_dict(sess: AccessSession, db: Session | None = None) -> dict:
    eng = db.get(Engineer, sess.engineer_id) if (db is not None and sess.engineer_id) else None
    dev = db.get(Device, sess.device_id) if db is not None else None
    return {
        "id": sess.id,
        "device_id": sess.device_id,
        "device_code": dev.device_code if dev else None,
        "direction": str(sess.direction),
        "state": str(sess.state),
        "reason_code": sess.reason_code,
        "reason": reason_text(sess.reason_code),
        "card_uid": sess.card_uid_raw,
        "card_id": sess.card_id,
        "engineer": ({"id": eng.id, "engineer_id": eng.engineer_id, "full_name": eng.full_name}
                     if eng else None),
        "request_id": sess.request_id,
        "face_score": sess.face_score,
        "presence_cm_start": sess.presence_cm_start,
        "presence_cm_final": sess.presence_cm_final,
        "created_at": sess.created_at.isoformat() if sess.created_at else None,
        "expires_at": sess.expires_at.isoformat() if sess.expires_at else None,
        "decided_at": sess.decided_at.isoformat() if sess.decided_at else None,
        "opened_at": sess.opened_at.isoformat() if sess.opened_at else None,
        "closed_at": sess.closed_at.isoformat() if sess.closed_at else None,
    }


def _emit(db: Session, sess: AccessSession, kind: str) -> None:
    defer(db, f"access.{kind}", session_dict(sess, db))


# ------------------------------------------------------------------ helpers
def _valid_distance(d: float | None) -> bool:
    return d is not None and 0 <= d <= 1000


def _present(dev: Device, d: float | None) -> bool:
    return _valid_distance(d) and d <= dev.presence_threshold_cm


def _explain_no_auth(db: Session, card_id: int, area_id: int, now) -> str:
    """Why ``find_in_force`` returned nothing — for the reason shown to the user. Never grants."""
    return explain_no_auth(db, now, card_id=card_id, area_ids=[area_id])


def explain_no_auth(db: Session, now, *, card_id: int | None = None, engineer_id: int | None = None,
                    area_ids: list[int] | None = None) -> str:
    """Reason code for "no authorization in force", by card (RFID door) or by engineer (QR).
    ``area_ids=None`` = any area. Never grants."""
    stmt = select(AuthorizationRequest)
    if card_id is not None:
        stmt = stmt.where(AuthorizationRequest.card_id == card_id)
    if engineer_id is not None:
        stmt = stmt.where(AuthorizationRequest.engineer_id == engineer_id)
    if card_id is None and engineer_id is None:
        return "NO_VALID_AUTH"
    if area_ids is not None:
        stmt = stmt.where(AuthorizationRequest.area_id.in_(area_ids))
    reqs = db.execute(stmt.order_by(AuthorizationRequest.created_at.desc()).limit(20)).scalars().all()
    if not reqs:
        return "NO_VALID_AUTH"
    covering = [r for r in reqs if r.start_at <= now < r.end_at]
    for r in covering:
        if r.status == RequestStatus.PENDING:
            return "REQUEST_PENDING"
    for r in covering:
        if r.status == RequestStatus.REVOKED:
            return "AUTH_REVOKED"
        if r.status == RequestStatus.REJECTED:
            return "AUTH_REJECTED"
    if any(r.status == RequestStatus.APPROVED and r.start_at > now for r in reqs):
        return "AUTH_NOT_STARTED"
    if any(r.status == RequestStatus.PENDING and r.start_at > now for r in reqs):
        return "REQUEST_PENDING"
    latest = reqs[0]
    if latest.status in (RequestStatus.EXPIRED, RequestStatus.FINISHED) or latest.end_at <= now:
        return "AUTH_EXPIRED"
    if latest.status == RequestStatus.REVOKED:
        return "AUTH_REVOKED"
    if latest.status == RequestStatus.REJECTED:
        return "AUTH_REJECTED"
    return "NO_VALID_AUTH"


def authorization_for_engineer(db: Session, engineer_id: int, area_ids: list[int] | None, now
                               ) -> tuple[AuthorizationRequest | None, str | None]:
    """Registro 2 check used outside the RFID flow (QR at the main entrance): ``(request, None)``
    if one is in force, else ``(None, reason_code)`` with the same codes as the door."""
    req = requests_service.find_in_force_for_engineer(db, engineer_id, area_ids, now)
    if req is not None:
        return req, None
    return None, explain_no_auth(db, now, engineer_id=engineer_id, area_ids=area_ids)


def _record_failure(db: Session, ctx: ActorCtx, sess: AccessSession, card: RfidCard | None) -> None:
    """Count the denial against the card; lock it after ``failure_max`` in the window."""
    if card is None or sess.reason_code not in _COUNTS_AS_FAILURE:
        return
    s = get_settings()
    card.failed_attempts = (card.failed_attempts or 0) + 1
    since = ctx.now - timedelta(minutes=s.failure_window_minutes)
    recent = db.execute(
        select(func.count()).select_from(AccessSession).where(
            AccessSession.card_id == card.id, AccessSession.state == ST.DENIED,
            AccessSession.reason_code.in_(_COUNTS_AS_FAILURE), AccessSession.decided_at >= since,
        )
    ).scalar_one()
    if recent >= s.failure_max and (card.locked_until is None or card.locked_until <= ctx.now):
        card.locked_until = ctx.now + timedelta(minutes=s.card_lock_minutes)
        ctx.audit(db, "card.locked", "card", card.id,
                  {"failures": recent, "until": card.locked_until.isoformat(), "session_id": sess.id})
        alerts.raise_alert(
            db, ctx, "REPEATED_FAILURES",
            f"{recent} intentos fallidos en {s.failure_window_minutes} min con la tarjeta {card.uid}; "
            f"bloqueada {s.card_lock_minutes} min",
            device_id=sess.device_id, engineer_id=card.engineer_id, session_id=sess.id,
        )


def _deny(db: Session, ctx: ActorCtx, sess: AccessSession, reason: str, card: RfidCard | None = None,
          *, extra: dict | None = None) -> AccessSession:
    sess.state = ST.DENIED
    sess.reason_code = reason
    sess.decided_at = ctx.now
    db.flush()
    ctx.audit(db, "access.denied", "access_session", sess.id, {
        "reason_code": reason, "direction": str(sess.direction), "card_uid": sess.card_uid_raw,
        "engineer_id": sess.engineer_id, "request_id": sess.request_id, **(extra or {}),
    })
    if reason in _ALERT_FOR:
        type_, sev = _ALERT_FOR[reason]
        alerts.raise_alert(db, ctx, type_, f"Acceso denegado ({sess.card_uid_raw}): {reason_text(reason)}",
                           severity=sev, device_id=sess.device_id, engineer_id=sess.engineer_id,
                           session_id=sess.id)
    _record_failure(db, ctx, sess, card)
    _emit(db, sess, "denied")
    return sess


def _engineer_inside(db: Session, engineer_id: int, device_id: int, now) -> bool:
    """Inside = the last *completed* door cycle of this engineer here was an ENTRADA, recently."""
    last = db.execute(
        select(AccessSession).where(
            AccessSession.engineer_id == engineer_id, AccessSession.device_id == device_id,
            AccessSession.opened_at.is_not(None),
        ).order_by(AccessSession.opened_at.desc()).limit(1)
    ).scalar_one_or_none()
    if last is None or last.direction != AccessDirection.ENTRY:
        return False
    return last.opened_at >= now - timedelta(hours=get_settings().exit_window_hours)


# Sentinel stored in card_uid_raw for exits requested with the inside button (never a valid
# hex UID, so it cannot collide with a real card).
BUTTON_UID = "EXIT_BUTTON"


def is_button_exit(sess: AccessSession) -> bool:
    return sess.direction == AccessDirection.EXIT and sess.card_uid_raw == BUTTON_UID


def engineers_inside(db: Session, device_id: int, now) -> list[int]:
    """Engineers whose last completed door cycle at this door was an ENTRADA, recently."""
    since = now - timedelta(hours=get_settings().exit_window_hours)
    rows = db.execute(
        select(AccessSession).where(
            AccessSession.device_id == device_id, AccessSession.engineer_id.is_not(None),
            AccessSession.opened_at.is_not(None), AccessSession.opened_at >= since,
        ).order_by(AccessSession.opened_at)
    ).scalars().all()
    last: dict[int, AccessSession] = {}
    for r in rows:
        last[r.engineer_id] = r
    return [eng_id for eng_id, r in last.items() if r.direction == AccessDirection.ENTRY]


def exit_button(db: Session, ctx: ActorCtx, dev: Device) -> AccessSession:
    """Inside exit button: opens ONLY if the backend knows someone is inside this door.

    No card, face or authorization (nobody may be trapped), and no presence check (the
    HC-SR04 watches the outside). With a single person inside the exit is attributed to them;
    with several it cannot be known who left, so it is recorded without engineer + INFO alert.
    """
    s = get_settings()
    now = ctx.now
    sess = AccessSession(
        device_id=dev.id, card_uid_raw=BUTTON_UID, state=ST.CARD_READ, created_at=now,
        expires_at=now + timedelta(seconds=s.access_session_timeout_s), direction=AccessDirection.EXIT,
    )
    db.add(sess)
    db.flush()
    ctx.audit(db, "access.exit_button", "access_session", sess.id, {"device": dev.device_code})
    if dev.status == DeviceStatus.DISABLED:
        return _deny(db, ctx, sess, "DEVICE_DISABLED")
    inside = engineers_inside(db, dev.id, now)
    if not inside:
        return _deny(db, ctx, sess, "NOBODY_INSIDE")
    if len(inside) == 1:
        sess.engineer_id = inside[0]
    else:
        alerts.raise_alert(db, ctx, "DEVICE_EVENT",
                           f"Salida por botón en {dev.device_code} con {len(inside)} personas dentro: "
                           "no se puede saber quién salió", severity=AlertSeverity.INFO,
                           device_id=dev.id, session_id=sess.id)
    sess.state = ST.FACE_OK  # nothing to verify: the decision is taken on the next poll
    ctx.audit(db, "access.exit_requested", "access_session", sess.id,
              {"engineer_id": sess.engineer_id, "inside": len(inside), "via": "button"})
    _emit(db, sess, "exit_requested")
    return sess


def _supersede_open_sessions(db: Session, ctx: ActorCtx, device_id: int, keep_id: str) -> None:
    """One door, one attempt at a time: a *valid* new card read (registered, linked card with
    presence) cancels any undecided attempt. Unknown cards never cancel someone else's."""
    for old in db.execute(
        select(AccessSession).where(AccessSession.device_id == device_id, AccessSession.id != keep_id,
                                    AccessSession.state.in_(PENDING_STATES))
    ).scalars():
        _deny(db, ctx, old, "SESSION_SUPERSEDED")


# ------------------------------------------------------------------ device: card read
def start(db: Session, ctx: ActorCtx, dev: Device, uid_raw: str, distance_cm: float | None) -> AccessSession:
    """Step 3 of the main flow. Returns the new session (DENIED, CARD_READ (exit) or AWAITING_FACE)."""
    s = get_settings()
    now = ctx.now
    sess = AccessSession(
        device_id=dev.id, card_uid_raw=(uid_raw or "")[:40], state=ST.CARD_READ, created_at=now,
        expires_at=now + timedelta(seconds=s.access_session_timeout_s),
        presence_cm_start=distance_cm if _valid_distance(distance_cm) else None,
        direction=AccessDirection.ENTRY,
    )
    db.add(sess)
    db.flush()
    ctx.audit(db, "access.card_read", "access_session", sess.id,
              {"card_uid": sess.card_uid_raw, "distance_cm": distance_cm})

    if dev.status == DeviceStatus.DISABLED:
        return _deny(db, ctx, sess, "DEVICE_DISABLED")

    try:
        uid = normalize_uid(uid_raw)
    except ValueError:
        return _deny(db, ctx, sess, "UNKNOWN_CARD")
    sess.card_uid_raw = uid
    card = db.execute(select(RfidCard).where(RfidCard.uid == uid)).scalar_one_or_none()
    if card is None:
        return _deny(db, ctx, sess, "UNKNOWN_CARD")
    sess.card_id = card.id
    sess.engineer_id = card.engineer_id
    if card.status != CardStatus.ACTIVE:
        return _deny(db, ctx, sess, "CARD_NOT_ACTIVE", card, extra={"card_status": str(card.status)})
    if card.engineer_id is None:
        return _deny(db, ctx, sess, "CARD_NOT_LINKED", card)
    eng = db.get(Engineer, card.engineer_id)
    _supersede_open_sessions(db, ctx, dev.id, sess.id)

    # Exit: face match required, authorization not (nobody may be trapped inside).
    if _engineer_inside(db, card.engineer_id, dev.id, now):
        sess.direction = AccessDirection.EXIT
        if eng is None or not eng.has_face:
            return _deny(db, ctx, sess, "NO_FACE_ENROLLED", card)
        if eng.status != EngineerStatus.ACTIVE or (card.locked_until is not None and card.locked_until > now):
            alerts.raise_alert(
                db, ctx, "INACTIVE_ENGINEER",
                f"Salida solicitada por {eng.engineer_id} con titular no activo o tarjeta bloqueada ({uid})",
                severity=AlertSeverity.CRITICAL, device_id=dev.id, engineer_id=eng.id, session_id=sess.id)
        sess.state = ST.AWAITING_FACE
        ctx.audit(db, "access.exit_requested", "access_session", sess.id, {"engineer_id": eng.id})
        _emit(db, sess, "awaiting_face")
        return sess

    if card.locked_until is not None and card.locked_until > now:
        return _deny(db, ctx, sess, "CARD_LOCKED", card, extra={"locked_until": card.locked_until.isoformat()})

    if eng is None or eng.status != EngineerStatus.ACTIVE:
        return _deny(db, ctx, sess, "ENGINEER_INACTIVE", card,
                     extra={"engineer_status": str(eng.status) if eng else None})

    req = requests_service.find_in_force(db, card.id, dev.area_id, now)
    if req is None:
        return _deny(db, ctx, sess, _explain_no_auth(db, card.id, dev.area_id, now), card)
    sess.request_id = req.id
    if not eng.has_face:
        return _deny(db, ctx, sess, "NO_FACE_ENROLLED", card)

    sess.state = ST.AWAITING_FACE
    ctx.audit(db, "access.awaiting_face", "access_session", sess.id,
              {"engineer_id": eng.id, "request_id": req.id})
    _emit(db, sess, "awaiting_face")
    return sess


# ------------------------------------------------------------------ kiosk: face result
def get_session(db: Session, session_id: str) -> AccessSession:
    sess = db.get(AccessSession, session_id, populate_existing=True) if isinstance(session_id, str) else None
    if sess is None:
        raise not_found("SESSION_NOT_FOUND", "Sesión de acceso no encontrada")
    return sess


def _expire_if_needed(db: Session, ctx: ActorCtx, sess: AccessSession) -> bool:
    if sess.state in PENDING_STATES and sess.expires_at is not None and sess.expires_at <= ctx.now:
        sess.state = ST.TIMEOUT
        sess.reason_code = "TIMEOUT"
        sess.decided_at = ctx.now
        ctx.audit(db, "access.timeout", "access_session", sess.id, {"engineer_id": sess.engineer_id})
        _emit(db, sess, "timeout")
        return True
    return False


def apply_face_result(db: Session, ctx: ActorCtx, session_id: str, ok: bool, score: float,
                      reason_code: str | None, *, matches: int = 0, frames: int = 0,
                      model_name: str | None = None) -> AccessSession:
    """Steps 12–14: record the 1:1 result computed by ``biometrics.verify`` (outside this
    transaction) and re-check that the authorization is still in force."""
    sess = get_session(db, session_id)
    if _expire_if_needed(db, ctx, sess):
        db.commit()
        return sess
    if sess.state != ST.AWAITING_FACE:
        raise DomainError("SESSION_NOT_AWAITING_FACE", "La sesión no está esperando verificación facial", 409)
    details = {"score": score, "matches": matches, "frames": frames, "model": model_name}
    sess.face_score = score
    card = db.get(RfidCard, sess.card_id) if sess.card_id else None
    if not ok:
        if reason_code in RETRYABLE_FACE:
            ctx.audit(db, "access.face_retry", "access_session", sess.id, {"reason_code": reason_code, **details})
            _emit(db, sess, "face_retry")
            db.commit()
            return sess
        _deny(db, ctx, sess, reason_code or "FACE_MISMATCH", card, extra=details)
        db.commit()
        return sess
    if sess.direction == AccessDirection.EXIT:  # exit: identity proven, no authorization needed
        sess.state = ST.FACE_OK
        ctx.audit(db, "access.face_ok", "access_session", sess.id, {**details, "direction": "SALIDA"})
        _emit(db, sess, "face_ok")
        db.commit()
        return sess
    dev = db.get(Device, sess.device_id)
    req = requests_service.find_in_force(db, sess.card_id, dev.area_id, ctx.now)
    if req is None or req.engineer_id != sess.engineer_id:
        _deny(db, ctx, sess, _explain_no_auth(db, sess.card_id, dev.area_id, ctx.now), card, extra=details)
        db.commit()
        return sess
    sess.state = ST.FACE_OK
    ctx.audit(db, "access.face_ok", "access_session", sess.id, details)
    _emit(db, sess, "face_ok")
    db.commit()
    return sess


# ------------------------------------------------------------------ device: polling
def poll(db: Session, ctx: ActorCtx, dev: Device, session_id: str, distance_cm: float | None) -> AccessSession:
    """Steps 6–7 and 15: the device asks for the decision, reporting the current distance."""
    s = get_settings()
    sess = get_session(db, session_id)
    if sess.device_id != dev.id:
        raise not_found("SESSION_NOT_FOUND", "Sesión de acceso no encontrada")
    if _expire_if_needed(db, ctx, sess):
        return sess
    if _valid_distance(distance_cm):
        sess.presence_cm_final = distance_cm

    if sess.state == ST.GRANTED:
        # Repeated poll (lost response): still valid only for a short time and if not opened.
        if sess.decided_at and sess.decided_at + timedelta(seconds=s.granted_valid_s) < ctx.now:
            sess.state = ST.TIMEOUT
            sess.reason_code = "TIMEOUT"
            ctx.audit(db, "access.grant_unused", "access_session", sess.id)
            _emit(db, sess, "timeout")
        return sess
    if sess.state not in PENDING_STATES:
        return sess

    if dev.status == DeviceStatus.DISABLED:
        return _deny(db, ctx, sess, "DEVICE_DISABLED")
    if is_button_exit(sess) and sess.state == ST.FACE_OK:
        return _grant(db, ctx, dev, sess, None)

    card = db.get(RfidCard, sess.card_id) if sess.card_id else None
    if sess.direction == AccessDirection.EXIT and sess.state == ST.FACE_OK:
        if card is None or card.status != CardStatus.ACTIVE or card.engineer_id != sess.engineer_id:
            return _deny(db, ctx, sess, "CARD_NOT_ACTIVE", card)
        return _grant(db, ctx, dev, sess, None)

    if sess.state == ST.FACE_OK:
        # Step 14: authorization must STILL be in force at the moment of opening.
        req = requests_service.find_in_force(db, sess.card_id, dev.area_id, ctx.now)
        if req is None or req.engineer_id != sess.engineer_id:
            return _deny(db, ctx, sess, _explain_no_auth(db, sess.card_id, dev.area_id, ctx.now), card)
        return _grant(db, ctx, dev, sess, req)
    return sess  # CARD_READ / AWAITING_FACE: keep waiting


def _grant(db: Session, ctx: ActorCtx, dev: Device, sess: AccessSession, req: AuthorizationRequest | None
           ) -> AccessSession:
    sess.state = ST.GRANTED
    sess.decided_at = ctx.now
    details: dict = {"direction": str(sess.direction), "engineer_id": sess.engineer_id,
                     "open_ms": dev.door_open_ms, "distance_cm": sess.presence_cm_final}
    if req is not None:
        req.use_count = (req.use_count or 0) + 1
        req.first_used_at = req.first_used_at or ctx.now
        details.update(request_id=req.id, use_count=req.use_count)
        defer(db, "request.updated", {"id": req.id, "use_count": req.use_count})
    card = db.get(RfidCard, sess.card_id) if sess.card_id else None
    if card is not None and sess.direction == AccessDirection.ENTRY:
        card.failed_attempts = 0
    ctx.audit(db, "access.granted", "access_session", sess.id, details)
    _emit(db, sess, "granted")
    return sess


def lcd_greeting(db: Session, sess: AccessSession) -> tuple[str, str]:
    """(greeting, name) for the door LCD, plain ASCII (HD44780 has no accents)."""
    greeting = "Hasta pronto" if sess.direction == AccessDirection.EXIT else "Bienvenido"
    eng = db.get(Engineer, sess.engineer_id) if sess.engineer_id else None
    return greeting, ascii_text(eng.full_name, 40) if eng else ""


def ascii_text(text: str, max_len: int) -> str:
    import unicodedata

    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return "".join(ch for ch in plain if 32 <= ord(ch) < 127).strip()[:max_len]


# ------------------------------------------------------------------ device: actuation
def confirm_opened(db: Session, ctx: ActorCtx, dev: Device, session_id: str, open_ms: int | None) -> AccessSession:
    """Step 16: the servo opened. For an ENTRADA this is the registered access."""
    sess = get_session(db, session_id)
    if sess.device_id != dev.id:
        raise not_found("SESSION_NOT_FOUND", "Sesión de acceso no encontrada")
    if sess.state == ST.OPENED:
        return sess  # idempotent retry
    if sess.state != ST.GRANTED:
        alerts.raise_alert(db, ctx, "DEVICE_EVENT",
                           f"{dev.device_code} informó apertura sin concesión (estado {sess.state})",
                           severity=AlertSeverity.CRITICAL, device_id=dev.id, session_id=sess.id)
        ctx.audit(db, "access.unexpected_open", "access_session", sess.id, {"state": str(sess.state)})
        db.commit()  # keep the alert even though the request fails
        raise DomainError("SESSION_NOT_GRANTED", "La sesión no tiene una concesión vigente", 409)
    sess.state = ST.OPENED
    sess.opened_at = ctx.now
    action = "access.entry" if sess.direction == AccessDirection.ENTRY else "access.exit_door_opened"
    ctx.audit(db, action, "access_session", sess.id,
              {"engineer_id": sess.engineer_id, "request_id": sess.request_id, "open_ms": open_ms})
    _emit(db, sess, "opened")
    return sess


def confirm_closed(db: Session, ctx: ActorCtx, dev: Device, session_id: str, reason: str) -> AccessSession:
    """Steps 17–18: the door closed; for a SALIDA this records the engineer's exit."""
    sess = get_session(db, session_id)
    if sess.device_id != dev.id:
        raise not_found("SESSION_NOT_FOUND", "Sesión de acceso no encontrada")
    if sess.state == ST.CLOSED:
        return sess
    if sess.state not in (ST.OPENED, ST.GRANTED):
        raise DomainError("SESSION_NOT_OPEN", "La puerta de esta sesión no está abierta", 409)
    if sess.opened_at is None:  # the "opened" confirmation was lost
        sess.opened_at = ctx.now
    sess.state = ST.CLOSED
    sess.closed_at = ctx.now
    ctx.audit(db, "access.door_closed", "access_session", sess.id,
              {"reason": reason, "direction": str(sess.direction)})
    if sess.direction == AccessDirection.EXIT:
        ctx.audit(db, "access.exit", "engineer", sess.engineer_id, {"session_id": sess.id, "device": dev.device_code})
    if reason == "EMERGENCY":
        alerts.raise_alert(db, ctx, "EMERGENCY_CLOSE", f"Cierre de emergencia en {dev.device_code}",
                           device_id=dev.id, session_id=sess.id)
    _emit(db, sess, "closed")
    return sess


# ------------------------------------------------------------------ device: telemetry
def device_status_dict(dev: Device) -> dict:
    hw = json.loads(dev.hw_status_json) if dev.hw_status_json else {}
    return {
        "id": dev.id, "device_code": dev.device_code, "name": dev.name, "status": str(dev.status),
        "area_id": dev.area_id, "firmware_version": dev.firmware_version,
        "last_seen_at": dev.last_seen_at.isoformat() if dev.last_seen_at else None,
        "presence_threshold_cm": dev.presence_threshold_cm, "door_open_ms": dev.door_open_ms,
        "hw": hw, "pending_command": dev.pending_command,
    }


_SENSOR_OK = {"rfid": "OK", "ultrasonic": "OK", "dht": "OK"}
# The DHT11 has its own alert (SENSOR_DHT_ERROR, raised by services.environment), not SENSOR_FAULT.
_SENSOR_FAULT_ALERTS = frozenset({"rfid", "ultrasonic"})


def _num(x: float) -> int | float:
    """27.0 → 27 (compact JSON for the firmware); keeps real decimals."""
    return int(x) if float(x).is_integer() else float(x)


def heartbeat(db: Session, ctx: ActorCtx, dev: Device, body: dict) -> dict:
    s = get_settings()
    prev = json.loads(dev.hw_status_json) if dev.hw_status_json else {}
    sensors = {k: str(v)[:12] for k, v in (body.get("sensors") or {}).items() if k in _SENSOR_OK}
    hw = {
        "state": body.get("state"), "door": body.get("door"), "present": body.get("present"),
        "distance_cm": body.get("distance_cm"), "rssi": body.get("rssi"), "uptime_s": body.get("uptime_s"),
        "free_heap": body.get("free_heap"), "session_id": body.get("session_id"), "sensors": sensors,
        "at": ctx.now.isoformat(),
    }
    dev.hw_status_json = json.dumps(hw, default=str)
    if body.get("fw"):
        dev.firmware_version = str(body["fw"])[:20]
    prev_sensors = prev.get("sensors") or {}
    for name, value in sensors.items():
        if name not in _SENSOR_FAULT_ALERTS:
            continue
        if value != "OK" and prev_sensors.get(name) != value:
            alerts.raise_alert(db, ctx, "SENSOR_FAULT",
                               f"{dev.device_code}: sensor {name} sin respuesta ({value})", device_id=dev.id)
            ctx.audit(db, "device.sensor_fault", "device", dev.id, {"sensor": name, "value": value})
        elif value == "OK" and prev_sensors.get(name) not in (None, "OK"):
            ctx.audit(db, "device.sensor_recovered", "device", dev.id, {"sensor": name})
    command = dev.pending_command if dev.pending_command == "EMERGENCY_CLOSE" else None
    if dev.pending_command:
        ctx.audit(db, "device.command_delivered", "device", dev.id, {"command": dev.pending_command})
        dev.pending_command = None
    defer(db, "device.status", device_status_dict(dev))
    return {
        "server_time": int(ctx.now.timestamp()),
        "config": {"presence_threshold_cm": dev.presence_threshold_cm, "door_open_ms": dev.door_open_ms,
                   "heartbeat_s": s.device_heartbeat_s,
                   # DHT11 thresholds (contract §4); the firmware applies them only if in range.
                   "temp_high_c": _num(s.temp_high_c), "temp_critical_c": _num(s.temp_critical_c),
                   "humidity_low_pct": _num(s.humidity_low_pct), "humidity_high_pct": _num(s.humidity_high_pct)},
        "command": command,
    }


def _door_in_use(db: Session, dev: Device, now) -> bool:
    """Someone is crossing the door right now (entering or leaving passes in front of the
    inside sensor): a grant being executed or a door cycle that ended moments ago."""
    grace = timedelta(seconds=get_settings().intrusion_door_grace_s)
    return db.execute(
        select(AccessSession.id).where(
            AccessSession.device_id == dev.id,
            (AccessSession.state.in_((ST.GRANTED, ST.OPENED)))
            | (AccessSession.closed_at >= now - grace)
            | ((AccessSession.state == ST.TIMEOUT) & (AccessSession.decided_at >= now - grace)),
        ).limit(1)
    ).first() is not None


def presence(db: Session, ctx: ActorCtx, dev: Device, present: bool, distance_cm: float | None) -> dict:
    """The HC-SR04 is INSIDE the room: someone detected while nobody authorized is inside (and
    no door cycle is happening) is an intrusion ⇒ CRITICAL alert and the device sounds the alarm.
    Returns the reply for the device: ``{"ok": true, "alarm": bool, "alarm_s": int}``."""
    s = get_settings()
    hw = json.loads(dev.hw_status_json) if dev.hw_status_json else {}
    hw.update(present=bool(present), distance_cm=distance_cm, at=ctx.now.isoformat())
    dev.hw_status_json = json.dumps(hw, default=str)
    ctx.audit(db, "device.presence", "device", dev.id, {"present": bool(present), "distance_cm": distance_cm})
    defer(db, "device.presence", {"device_id": dev.id, "device_code": dev.device_code,
                                  "present": bool(present), "distance_cm": distance_cm})
    alarm = False
    if present:
        inside = engineers_inside(db, dev.id, ctx.now)
        if not inside and not _door_in_use(db, dev, ctx.now):
            alarm = True
            ctx.audit(db, "device.intrusion", "device", dev.id, {"distance_cm": distance_cm})
            alerts.raise_alert(db, ctx, "INTRUSION",
                               f"Intrusión en {dev.device_code}: el sensor interior detecta a alguien "
                               f"a {distance_cm} cm y no hay nadie autorizado dentro",
                               device_id=dev.id, dedupe_s=s.intrusion_alarm_s)
    return {"ok": True, "alarm": alarm, "alarm_s": s.intrusion_alarm_s}


def device_event(db: Session, ctx: ActorCtx, dev: Device, type_: str, detail: str | None) -> None:
    ctx.audit(db, "device.event", "device", dev.id, {"type": type_, "detail": detail})
    sev = AlertSeverity.CRITICAL if type_ == "BAD_RESPONSE_SIGNATURE" else AlertSeverity.WARN
    alerts.raise_alert(db, ctx, "SENSOR_FAULT" if type_ == "SENSOR_FAULT" else "DEVICE_EVENT",
                       f"{dev.device_code}: {type_}" + (f" — {detail}" if detail else ""),
                       severity=sev, device_id=dev.id, dedupe_s=30)


def request_emergency_close(db: Session, ctx: ActorCtx, device_id: int) -> Device:
    dev = db.get(Device, device_id, options=[selectinload(Device.area)], populate_existing=True)
    if dev is None:
        raise not_found("DEVICE_NOT_FOUND", "Dispositivo no encontrado")
    dev.pending_command = "EMERGENCY_CLOSE"
    ctx.audit(db, "device.emergency_close_requested", "device", dev.id)
    defer(db, "device.status", device_status_dict(dev))
    db.commit()
    return dev


# ------------------------------------------------------------------ scheduler sweeps
def sweep(db: Session, now=None) -> dict[str, int]:
    """Time out stale sessions and mark silent devices OFFLINE. Idempotent."""
    s = get_settings()
    ctx = ActorCtx.system(now)
    counts = {"timeouts": 0, "offline": 0}
    for sess in db.execute(
        select(AccessSession).where(AccessSession.state.in_(PENDING_STATES), AccessSession.expires_at <= ctx.now)
    ).scalars():
        if _expire_if_needed(db, ctx, sess):
            counts["timeouts"] += 1
    for sess in db.execute(
        select(AccessSession).where(
            AccessSession.state == ST.GRANTED,
            AccessSession.decided_at <= ctx.now - timedelta(seconds=s.granted_valid_s),
        )
    ).scalars():
        sess.state = ST.TIMEOUT
        sess.reason_code = "TIMEOUT"
        ctx.audit(db, "access.grant_unused", "access_session", sess.id)
        _emit(db, sess, "timeout")
        counts["timeouts"] += 1
    stale = ctx.now - timedelta(seconds=s.device_offline_s)
    for dev in db.execute(
        select(Device).where(Device.status == DeviceStatus.ONLINE,
                             (Device.last_seen_at.is_(None)) | (Device.last_seen_at < stale))
    ).scalars():
        dev.status = DeviceStatus.OFFLINE
        ctx.audit(db, "device.offline", "device", dev.id,
                  {"last_seen_at": dev.last_seen_at.isoformat() if dev.last_seen_at else None})
        alerts.raise_alert(db, ctx, "DEVICE_OFFLINE",
                           f"{dev.device_code} sin latido desde hace más de {s.device_offline_s} s",
                           device_id=dev.id)
        defer(db, "device.status", device_status_dict(dev))
        counts["offline"] += 1
    db.commit()
    return counts


def device_ctx(device: Device, correlation_id: str | None, now=None) -> ActorCtx:
    ctx = ActorCtx(ActorType.DEVICE, device.id, correlation_id)
    if now is not None:
        ctx.now = now
    return ctx
