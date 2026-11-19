"""QR credentials for the main entrance (contract §2). Identification only — never access.

- QR text: ``DCG-QR1:<token>`` with ``token = secrets.token_urlsafe(24)`` (32 chars).
- Only ``sha256(token)`` and a 6-char display prefix are stored; the full text is returned
  **once**, when issued.
- At most one ACTIVA credential per engineer: issuing a new one revokes the previous one.
  (Writes run under ``BEGIN IMMEDIATE``, so two concurrent issues cannot both stay active.)
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import DomainError, not_found
from app.db.types import utcnow
from app.models import Engineer, QrCredential
from app.models.enums import EngineerStatus, QrStatus
from app.services.context import ActorCtx

QR_PREFIX = "DCG-QR1:"
TOKEN_BYTES = 24  # token_urlsafe(24) → 32 URL-safe characters
QR_TEXT_RE = re.compile(r"^DCG-QR1:([A-Za-z0-9_-]{32})$")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def parse(qr_text: str) -> str | None:
    """Token inside a well-formed QR text, or None."""
    m = QR_TEXT_RE.fullmatch(qr_text.strip()) if isinstance(qr_text, str) else None
    return m.group(1) if m else None


def _engineer(db: Session, engineer_pk: int) -> Engineer:
    eng = db.get(Engineer, engineer_pk, populate_existing=True)
    if eng is None:
        raise not_found("ENGINEER_NOT_FOUND", "Ingeniero no encontrado")
    return eng


def active_for(db: Session, engineer_pk: int) -> QrCredential | None:
    return db.execute(
        select(QrCredential).where(QrCredential.engineer_id == engineer_pk, QrCredential.status == QrStatus.ACTIVE)
        .order_by(QrCredential.id.desc()).limit(1)
    ).scalar_one_or_none()


def _revoke_all(db: Session, ctx: ActorCtx, engineer_pk: int, cause: str) -> int:
    n = 0
    for cred in db.execute(
        select(QrCredential).where(QrCredential.engineer_id == engineer_pk, QrCredential.status == QrStatus.ACTIVE)
    ).scalars():
        cred.status = QrStatus.REVOKED
        cred.revoked_at = ctx.now
        cred.revoked_by = ctx.actor_id if isinstance(ctx.actor_id, int) else None
        ctx.audit(db, "qr.revoked", "qr_credential", cred.id,
                  {"engineer_id": engineer_pk, "prefix": cred.prefix, "cause": cause})
        n += 1
    return n


def issue(db: Session, ctx: ActorCtx, engineer_pk: int, expires_at: datetime | None, *,
          valid_minutes: int | None = None, single_use: bool = False) -> dict:
    """New credential for an ACTIVO engineer. Returns the QR text (shown only this once).

    Temporary pass: ``valid_minutes`` (counted from now, on the server's clock) or ``expires_at``.
    ``single_use`` passes (visits, suppliers) must be temporary and are consumed by the first
    GRANTED scan; a permanent single-use pass would stay a bearer token forever, so it is refused.
    """
    eng = _engineer(db, engineer_pk)
    if eng.status != EngineerStatus.ACTIVE:
        raise DomainError("ENGINEER_NOT_ACTIVE", "Solo se emite un QR a ingenieros en estado ACTIVO", 409)
    if valid_minutes is not None:
        if expires_at is not None:
            raise DomainError("QR_EXPIRY_AMBIGUOUS", "Indica valid_minutes o expires_at, no ambos", 422)
        expires_at = ctx.now + timedelta(minutes=valid_minutes)
    if expires_at is not None and expires_at <= ctx.now:
        raise DomainError("QR_EXPIRES_IN_PAST", "La fecha de vencimiento debe ser futura", 422)
    if single_use and expires_at is None:
        raise DomainError("QR_SINGLE_USE_NEEDS_EXPIRY",
                          "Un pase de un solo uso debe tener vencimiento (valid_minutes o expires_at)", 422)
    replaced = _revoke_all(db, ctx, eng.id, "replaced")
    token = secrets.token_urlsafe(TOKEN_BYTES)
    cred = QrCredential(engineer_id=eng.id, token_sha256=token_hash(token), prefix=token[:6],
                        status=QrStatus.ACTIVE, expires_at=expires_at, single_use=single_use, created_at=ctx.now,
                        created_by=ctx.actor_id if isinstance(ctx.actor_id, int) else None)
    db.add(cred)
    db.flush()
    ctx.audit(db, "qr.issued", "qr_credential", cred.id,
              {"engineer_id": eng.id, "prefix": cred.prefix, "replaced": replaced, "single_use": single_use,
               "expires_at": expires_at.isoformat() if expires_at else None})  # never the token
    db.commit()
    return {"qr_text": QR_PREFIX + token, "prefix": cred.prefix, "expires_at": cred.expires_at,
            "single_use": cred.single_use,
            "engineer": {"id": eng.id, "full_name": eng.full_name, "position": eng.position}}


def status(db: Session, engineer_pk: int) -> dict:
    _engineer(db, engineer_pk)
    cred = active_for(db, engineer_pk)
    if cred is None:
        return {"active": False, "expired": False, "single_use": False, "prefix": None, "created_at": None,
                "expires_at": None, "last_used_at": None}
    expired = cred.expires_at is not None and cred.expires_at <= utcnow()
    return {"active": True, "expired": expired, "single_use": cred.single_use, "prefix": cred.prefix,
            "created_at": cred.created_at, "expires_at": cred.expires_at, "last_used_at": cred.last_used_at}


def consume(db: Session, ctx: ActorCtx, cred: QrCredential) -> None:
    """A single-use pass is spent by its first granted scan: it is revoked at once, so a photo of
    the code is useless afterwards. Caller commits."""
    cred.status = QrStatus.REVOKED
    cred.revoked_at = ctx.now
    ctx.audit(db, "qr.consumed", "qr_credential", cred.id, {"engineer_id": cred.engineer_id, "prefix": cred.prefix})


def revoke(db: Session, ctx: ActorCtx, engineer_pk: int) -> None:
    _engineer(db, engineer_pk)
    if not _revoke_all(db, ctx, engineer_pk, "admin"):
        raise not_found("QR_NOT_FOUND", "El ingeniero no tiene un QR activo")
    db.commit()


def revoke_for_engineer(db: Session, ctx: ActorCtx, engineer_pk: int, cause: str) -> int:
    """Used by other services (e.g. data erasure). Caller commits."""
    return _revoke_all(db, ctx, engineer_pk, cause)


def find_by_token(db: Session, token: str) -> QrCredential | None:
    return db.execute(
        select(QrCredential).where(QrCredential.token_sha256 == token_hash(token))
    ).scalar_one_or_none()
