"""Face kiosk next to the door (steps 11–13): shows who must look at the camera and sends frames.

Auth: ``X-Kiosk-Token`` (see ``kiosk_token()``) or an admin session. The 1:1 comparison runs
in a worker thread with a *read* session; only the short result write takes the DB lock.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.api.deps import ReadDb, _extract_token
from app.api.v1.uploads import read_images
from app.core.config import get_settings
from app.core.errors import DomainError
from app.db.session import ReadSessionLocal, SessionLocal
from app.db.types import utcnow
from app.models import AccessSession, Device, Engineer
from app.models.enums import AccessDirection, AccessState, ActorType, AdminRole
from app.services import access_engine as engine
from app.services import biometrics
from app.services.auth import admin_from_token
from app.services.context import ActorCtx

kiosk = APIRouter(prefix="/kiosk", tags=["kiosk (verificación facial)"])
vision_verify = APIRouter(prefix="/vision", tags=["kiosk (verificación facial)"])


def kiosk_token() -> str:
    s = get_settings()
    if s.kiosk_token:
        return s.kiosk_token
    return hmac.new(s.master_key.encode(), b"dc-guardian/kiosk/v1", hashlib.sha256).hexdigest()[:40]


def kiosk_principal(request: Request, db: ReadDb) -> ActorCtx:
    """Kiosk token or admin session (auditors are read-only and cannot drive the door)."""
    cid = request.state.correlation_id
    token = request.headers.get("x-kiosk-token")
    if token:
        if hmac.compare_digest(token.encode(), kiosk_token().encode()):
            # Audited as actor "system/kiosk", distinguishable from the scheduler ("system/None").
            return ActorCtx(ActorType.SYSTEM, "kiosk", cid)  # type: ignore[arg-type]
        raise DomainError("KIOSK_TOKEN_INVALID", "Token de kiosco inválido", 401)
    jwt_token = _extract_token(request)
    if not jwt_token:
        raise DomainError("UNAUTHENTICATED", "Se requiere token de kiosco o sesión de administrador", 401)
    admin = admin_from_token(db, jwt_token)
    if admin.role != AdminRole.ADMIN:
        raise DomainError("FORBIDDEN", "Permisos insuficientes", 403)
    return ActorCtx(ActorType.ADMIN, admin.id, cid)


KioskCtx = Annotated[ActorCtx, Depends(kiosk_principal)]


@kiosk.get("/pending")
def pending(ctx: KioskCtx, db: ReadDb, device_code: Annotated[str, Query(max_length=30)] = "DC-DOOR-01"):
    """The attempt waiting for a face at this door (or ``null``)."""
    dev = db.execute(select(Device).where(Device.device_code == device_code.upper())).scalar_one_or_none()
    if dev is None:
        raise DomainError("DEVICE_NOT_FOUND", "Dispositivo no encontrado", 404)
    sess = db.execute(
        select(AccessSession).where(AccessSession.device_id == dev.id, AccessSession.state == AccessState.AWAITING_FACE)
        .order_by(AccessSession.created_at.desc()).limit(1)
    ).scalar_one_or_none()
    out = {"device": {"device_code": dev.device_code, "name": dev.name}, "session": None,
           "frames": get_settings().face_frames}
    if sess is not None and sess.expires_at > ctx.now:
        eng = db.get(Engineer, sess.engineer_id)
        out["session"] = {"id": sess.id, "expires_at": sess.expires_at.isoformat(),
                          "engineer": {"engineer_id": eng.engineer_id, "full_name": eng.full_name} if eng else None}
    return out


def verify_frames(session_id: str, frames: list[bytes], ctx: ActorCtx) -> dict:
    """Run 1:1 verification for an AWAITING_FACE session and apply the result. Sync (thread)."""
    with ReadSessionLocal() as rdb:
        sess = rdb.get(AccessSession, session_id)
        if sess is None:
            raise DomainError("SESSION_NOT_FOUND", "Sesión de acceso no encontrada", 404)
        if sess.state != AccessState.AWAITING_FACE:
            raise DomainError("SESSION_NOT_AWAITING_FACE", "La sesión no está esperando verificación facial", 409)
        engineer_pk = sess.engineer_id
        is_exit = sess.direction == AccessDirection.EXIT
        # CPU work, no write lock held. Exit: identity only (a suspended engineer may leave).
        result = biometrics.verify(rdb, engineer_pk, frames, allow_inactive=is_exit)
    with SessionLocal() as db:
        ctx.now = utcnow()  # decision time = after the comparison
        sess = engine.apply_face_result(db, ctx, session_id, result.ok, result.score, result.reason_code,
                                        matches=result.matches, frames=result.frames,
                                        model_name=result.model_name)
        return {
            "session_id": sess.id, "state": str(sess.state), "reason_code": sess.reason_code,
            "reason": engine.reason_text(sess.reason_code), "face_reason_code": result.reason_code,
            "score": result.score, "matches": result.matches, "frames": result.frames,
            "retry": result.reason_code in engine.RETRYABLE_FACE and sess.state == AccessState.AWAITING_FACE,
        }


@vision_verify.post("/verify")
async def verify(request: Request, ctx: KioskCtx):
    """multipart: ``session_id`` + exactly N ``frames`` (N = DCG_FACE_FRAMES, distinct captures ~200 ms
    apart). Read only after auth, in memory, never written to disk."""
    s = get_settings()
    form = await read_images(request, "frames", s.face_frames)
    session_id = form.fields.get("session_id", "")
    if len(session_id) != 32 or any(c not in "0123456789abcdef" for c in session_id):
        raise DomainError("VALIDATION_ERROR", "session_id inválido", 422)
    return await run_in_threadpool(verify_frames, session_id, [data for _, data in form.files], ctx)
