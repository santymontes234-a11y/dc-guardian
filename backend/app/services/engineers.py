"""REGISTRO 1 — engineers. Creating or editing an engineer never grants access.

Access is decided exclusively from REGISTRO 2 (``authorization_requests``).
"""

from __future__ import annotations

import re

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.errors import DomainError, not_found
from app.models import Engineer
from app.models.engineer import ENGINEER_ID_PREFIX
from app.models.enums import CardStatus, EngineerStatus
from app.schemas.common import PageParams
from app.schemas.engineers import EngineerCreate, EngineerUpdate
from app.services import requests as requests_service
from app.services.context import ActorCtx, diff_fields

_ID_RE = re.compile(r"^ENG-(\d+)$")
ERASED_NAME = "[Datos eliminados]"
ERASED_TEXT = "—"


def _check_email(db: Session, email: str, exclude_id: int | None = None) -> str:
    email = email.strip().lower()
    domain = get_settings().institutional_email_domain
    if domain and not email.endswith("@" + domain.lower()):
        raise DomainError("EMAIL_NOT_INSTITUTIONAL", f"El correo debe ser @{domain}", 422)
    q = select(Engineer.id).where(func.lower(Engineer.institutional_email) == email)
    if exclude_id is not None:
        q = q.where(Engineer.id != exclude_id)
    if db.execute(q).first():
        raise DomainError("EMAIL_TAKEN", "Ya existe un ingeniero con ese correo institucional", 409)
    return email


def next_engineer_id(db: Session) -> str:
    """Next sequential ID (ENG-0001, ENG-0002, ...). IDs of erased engineers are never reused."""
    highest = 0
    for (code,) in db.execute(select(Engineer.engineer_id)):
        m = _ID_RE.match(code or "")
        if m:
            highest = max(highest, int(m.group(1)))
    return f"{ENGINEER_ID_PREFIX}{highest + 1:04d}"


def get(db: Session, engineer_pk: int) -> Engineer:
    eng = db.get(
        Engineer,
        engineer_pk,
        options=[selectinload(Engineer.cards), selectinload(Engineer.face_embeddings)],
        populate_existing=True,
    )
    if eng is None:
        raise not_found("ENGINEER_NOT_FOUND", "Ingeniero no encontrado")
    return eng


def get_by_engineer_id(db: Session, engineer_id: str) -> Engineer:
    pk = db.execute(select(Engineer.id).where(Engineer.engineer_id == engineer_id.upper())).scalar_one_or_none()
    if pk is None:
        raise not_found("ENGINEER_NOT_FOUND", "Ingeniero no encontrado")
    return get(db, pk)


def ensure_not_erased(eng: Engineer) -> None:
    if eng.status == EngineerStatus.ERASED:
        raise DomainError("ENGINEER_ERASED", "Los datos de este ingeniero fueron eliminados", 409)


def list_(
    db: Session, page: PageParams, *, status: EngineerStatus | None = None, q: str | None = None,
    has_face: bool | None = None,
) -> tuple[list[Engineer], int]:
    stmt = select(Engineer)
    if status:
        stmt = stmt.where(Engineer.status == status)
    else:  # erased records are history: listed only when explicitly requested
        stmt = stmt.where(Engineer.status != EngineerStatus.ERASED)
    if has_face is not None:
        col = Engineer.face_embedding_reference
        stmt = stmt.where(col.is_not(None) if has_face else col.is_(None))
    if q:
        stmt = stmt.where(
            or_(
                Engineer.full_name.icontains(q, autoescape=True),
                Engineer.engineer_id.icontains(q, autoescape=True),
                Engineer.institutional_email.icontains(q, autoescape=True),
                Engineer.department.icontains(q, autoescape=True),
                Engineer.position.icontains(q, autoescape=True),
            )
        )
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(
        stmt.options(selectinload(Engineer.cards), selectinload(Engineer.face_embeddings))
        .order_by(Engineer.engineer_id)
        .limit(page.limit)
        .offset(page.offset)
    ).scalars().all()
    return list(rows), total


def stats(db: Session) -> dict[str, int]:
    rows = db.execute(select(Engineer.status, func.count()).group_by(Engineer.status)).all()
    out = {s.value: 0 for s in EngineerStatus}
    out.update({s.value: n for s, n in rows})
    out["CON_ROSTRO"] = db.execute(
        select(func.count()).where(Engineer.face_embedding_reference.is_not(None),
                                   Engineer.status != EngineerStatus.ERASED)
    ).scalar_one()
    return out


def create(db: Session, ctx: ActorCtx, data: EngineerCreate) -> Engineer:
    email = _check_email(db, data.institutional_email)
    engineer_id = next_engineer_id(db)  # write session (BEGIN IMMEDIATE) → no concurrent duplicate
    if db.execute(select(Engineer.id).where(Engineer.engineer_id == engineer_id)).first():
        raise DomainError("ENGINEER_ID_TAKEN", "Ya existe un ingeniero con ese ID", 409)
    eng = Engineer(
        engineer_id=engineer_id,
        full_name=data.full_name,
        department=data.department,
        position=data.position,
        institutional_email=email,
        status=data.status,
    )
    db.add(eng)
    db.flush()
    # Personal data is deliberately left out of the (immutable) audit log.
    ctx.audit(db, "engineer.created", "engineer", eng.id, {"engineer_id": eng.engineer_id, "status": eng.status})
    db.commit()
    return get(db, eng.id)


def update(db: Session, ctx: ActorCtx, engineer_pk: int, data: EngineerUpdate) -> Engineer:
    eng = get(db, engineer_pk)
    ensure_not_erased(eng)
    changes = data.model_dump(exclude_unset=True, exclude_none=True)
    if "institutional_email" in changes:
        changes["institutional_email"] = _check_email(db, changes["institutional_email"], exclude_id=eng.id)
    diff = diff_fields(eng, changes)
    if diff:
        # Only the names of the changed fields: values are personal data and the log is append-only.
        ctx.audit(db, "engineer.updated", "engineer", eng.id,
                  {"engineer_id": eng.engineer_id, "fields": sorted(diff)})
        db.commit()
    return get(db, eng.id)


def change_status(
    db: Session, ctx: ActorCtx, engineer_pk: int, status: EngineerStatus, reason: str
) -> tuple[Engineer, int, int]:
    """Deactivating/suspending closes every open authorization of the engineer (fail-closed)."""
    eng = get(db, engineer_pk)
    ensure_not_erased(eng)
    if status == EngineerStatus.ERASED:
        raise DomainError("USE_ERASURE", "Usa la eliminación de datos para este estado", 422)
    if eng.status == status:
        raise DomainError("STATUS_UNCHANGED", "El ingeniero ya tiene ese estado", 409)
    old = eng.status
    eng.status = status
    revoked = rejected = 0
    if status != EngineerStatus.ACTIVE:
        revoked, rejected = requests_service.close_open_requests(
            db, ctx, engineer_id=eng.id, note=f"Ingeniero {status.value}: {reason}"
        )
    ctx.audit(db, "engineer.status_changed", "engineer", eng.id,
              {"engineer_id": eng.engineer_id, "from": old, "to": status, "reason": reason,
               "revoked": revoked, "rejected": rejected})
    db.commit()
    return get(db, eng.id), revoked, rejected


def erase(db: Session, ctx: ActorCtx, engineer_pk: int, confirm_engineer_id: str, reason: str) -> dict:
    """Right to erasure: delete personal and biometric data, keep an anonymous row for history.

    The row keeps only ``engineer_id`` (never reused) so authorizations, access sessions and
    the hash-chained audit log stay consistent. Open requests are closed and active cards
    unlinked first (fail-closed). Irreversible.
    """
    eng = get(db, engineer_pk)
    ensure_not_erased(eng)
    if confirm_engineer_id != eng.engineer_id:
        raise DomainError("CONFIRMATION_MISMATCH", "El ID de confirmación no coincide", 422)

    revoked, rejected = requests_service.close_open_requests(
        db, ctx, engineer_id=eng.id, note=f"Datos del ingeniero eliminados: {reason}"
    )
    unlinked = 0
    for card in list(eng.cards):
        if card.status in (CardStatus.ACTIVE, CardStatus.BLOCKED):
            card.engineer_id = None
            card.assigned_at = None
            card.failed_attempts = 0
            card.locked_until = None
            ctx.audit(db, "card.unassigned", "card", card.id, {"engineer_id": [eng.id, None], "cause": "erasure"})
            unlinked += 1

    samples = len(eng.face_embeddings)
    eng.face_embeddings.clear()  # delete-orphan → rows deleted
    db.flush()
    eng.face_embedding_reference = None
    eng.full_name = ERASED_NAME
    eng.department = ERASED_TEXT
    eng.position = ERASED_TEXT
    eng.institutional_email = f"eliminado.{eng.engineer_id.lower()}@invalid"
    eng.status = EngineerStatus.ERASED
    ctx.audit(db, "engineer.erased", "engineer", eng.id,
              {"engineer_id": eng.engineer_id, "reason": reason, "revoked": revoked, "rejected": rejected,
               "cards_unlinked": unlinked, "face_samples_deleted": samples})
    db.commit()
    return {"engineer": get(db, eng.id), "requests_revoked": revoked, "requests_rejected": rejected,
            "cards_unlinked": unlinked, "face_samples_deleted": samples}


