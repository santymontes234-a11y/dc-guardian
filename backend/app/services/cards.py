"""RFID cards: registration, binding to an engineer, lifecycle.

Card lifecycle:
    ACTIVA ⇄ BLOQUEADA     (temporary; open requests stay, the access engine denies meanwhile)
    ACTIVA/BLOQUEADA → PERDIDA → BAJA
    any → BAJA             (terminal)
PERDIDA and BAJA close every open request of the card. A lost card is never reactivated:
register a new one.
"""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import DomainError, not_found
from app.models import Engineer, RfidCard
from app.models.enums import CardStatus, EngineerStatus
from app.schemas.common import PageParams
from app.schemas.facility import CardCreate
from app.services import requests as requests_service
from app.services.context import ActorCtx

C = CardStatus
CARD_TRANSITIONS: dict[CardStatus, frozenset[CardStatus]] = {
    C.ACTIVE: frozenset({C.BLOCKED, C.LOST, C.RETIRED}),
    C.BLOCKED: frozenset({C.ACTIVE, C.LOST, C.RETIRED}),
    C.LOST: frozenset({C.RETIRED}),
    C.RETIRED: frozenset(),
}


def get(db: Session, card_id: int) -> RfidCard:
    card = db.get(RfidCard, card_id, options=[selectinload(RfidCard.engineer)], populate_existing=True)
    if card is None:
        raise not_found("CARD_NOT_FOUND", "Tarjeta no encontrada")
    return card


def get_by_uid(db: Session, uid: str) -> RfidCard | None:
    return db.execute(select(RfidCard).where(RfidCard.uid == uid)).scalar_one_or_none()


def list_(db: Session, page: PageParams, *, status: CardStatus | None = None, engineer_id: int | None = None,
          unassigned: bool = False, q: str | None = None) -> tuple[list[RfidCard], int]:
    stmt = select(RfidCard)
    if status:
        stmt = stmt.where(RfidCard.status == status)
    if engineer_id:
        stmt = stmt.where(RfidCard.engineer_id == engineer_id)
    if unassigned:
        stmt = stmt.where(RfidCard.engineer_id.is_(None))
    if q:
        stmt = stmt.where(or_(RfidCard.uid.icontains(q, autoescape=True), RfidCard.label.icontains(q, autoescape=True)))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(
        stmt.options(selectinload(RfidCard.engineer)).order_by(RfidCard.id).limit(page.limit).offset(page.offset)
    ).scalars().all()
    return list(rows), total


def _active_engineer(db: Session, engineer_id: int) -> Engineer:
    eng = db.get(Engineer, engineer_id)
    if eng is None:
        raise not_found("ENGINEER_NOT_FOUND", "Ingeniero no encontrado")
    if eng.status != EngineerStatus.ACTIVE:
        raise DomainError("ENGINEER_NOT_ACTIVE", "Solo se pueden asignar tarjetas a ingenieros activos", 409)
    return eng


def create(db: Session, ctx: ActorCtx, data: CardCreate) -> RfidCard:
    if get_by_uid(db, data.uid):
        raise DomainError("CARD_UID_TAKEN", "Esa tarjeta (UID) ya está registrada", 409)
    card = RfidCard(uid=data.uid, label=data.label, status=C.ACTIVE)
    if data.engineer_id is not None:
        _active_engineer(db, data.engineer_id)
        card.engineer_id = data.engineer_id
        card.assigned_at = ctx.now
    db.add(card)
    db.flush()
    ctx.audit(db, "card.created", "card", card.id, {"uid": card.uid, "engineer_id": card.engineer_id})
    db.commit()
    return get(db, card.id)


def update_label(db: Session, ctx: ActorCtx, card_id: int, label: str | None) -> RfidCard:
    card = get(db, card_id)
    if card.label != label:
        ctx.audit(db, "card.updated", "card", card.id, {"label": [card.label, label]})
        card.label = label
        db.commit()
    return get(db, card.id)


def assign(db: Session, ctx: ActorCtx, card_id: int, engineer_id: int | None) -> RfidCard:
    card = get(db, card_id)
    if card.status in (C.LOST, C.RETIRED):
        raise DomainError("CARD_NOT_ASSIGNABLE", f"Una tarjeta {card.status.value} no puede asignarse", 409)
    if card.engineer_id == engineer_id:
        raise DomainError("ASSIGNMENT_UNCHANGED", "La tarjeta ya tiene esa asignación", 409)
    if requests_service.has_open_requests(db, card_id=card.id):
        raise DomainError(
            "CARD_HAS_OPEN_REQUESTS",
            "La tarjeta tiene solicitudes pendientes o aprobadas; ciérralas antes de reasignarla", 409,
        )
    if engineer_id is not None:
        _active_engineer(db, engineer_id)
    old = card.engineer_id
    card.engineer_id = engineer_id
    card.assigned_at = ctx.now if engineer_id is not None else None
    card.failed_attempts = 0
    card.locked_until = None
    ctx.audit(db, "card.assigned" if engineer_id else "card.unassigned", "card", card.id,
              {"engineer_id": [old, engineer_id]})
    db.commit()
    return get(db, card.id)


def change_status(db: Session, ctx: ActorCtx, card_id: int, status: CardStatus, reason: str
                  ) -> tuple[RfidCard, int, int]:
    card = get(db, card_id)
    if status not in CARD_TRANSITIONS[card.status]:
        raise DomainError("INVALID_TRANSITION", f"No se puede pasar de {card.status.value} a {status.value}", 409)
    old = card.status
    card.status = status
    revoked = rejected = 0
    if status in (C.LOST, C.RETIRED):
        revoked, rejected = requests_service.close_open_requests(
            db, ctx, card_id=card.id, note=f"Tarjeta {status.value}: {reason}"
        )
    if status == C.ACTIVE:
        card.failed_attempts = 0
        card.locked_until = None
    ctx.audit(db, "card.status_changed", "card", card.id,
              {"from": old, "to": status, "reason": reason, "revoked": revoked, "rejected": rejected})
    db.commit()
    return get(db, card.id), revoked, rejected


def unlock(db: Session, ctx: ActorCtx, card_id: int) -> RfidCard:
    """Clear the temporary lock set by repeated failed access attempts (F5)."""
    card = get(db, card_id)
    card.failed_attempts = 0
    card.locked_until = None
    ctx.audit(db, "card.unlocked", "card", card.id)
    db.commit()
    return get(db, card.id)
