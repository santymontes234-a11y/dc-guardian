"""REGISTRO 2 — authorization requests and their state machine (design doc §2.5).

    PENDIENTE ──approve──► APROBADA ──(window ends, used)──► FINALIZADA
        │                     │  ├──(window ends, unused)──► EXPIRADA
        │ reject              │  ├──revoke────────────────► REVOCADA
        ▼                     │  └──finalize (manual)─────► FINALIZADA
    RECHAZADA                 │
    PENDIENTE ──(window ends without review)──────────────► EXPIRADA

Terminal states never reopen; a new request must be created instead.

Separation of duties: an admin linked to an engineer record (``admins.engineer_id``) can never
approve or reject that engineer's requests — nobody authorizes themselves.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.errors import DomainError, not_found
from app.models import Admin, Area, AuthorizationRequest, Engineer, RfidCard
from app.models.enums import ActorType, CardStatus, EngineerStatus, RequestStatus
from app.schemas.common import PageParams
from app.schemas.requests import RequestCreate, RequestStats
from app.services.context import ActorCtx

S = RequestStatus
OPEN_STATUSES = (S.PENDING, S.APPROVED)

TRANSITIONS: dict[RequestStatus, frozenset[RequestStatus]] = {
    S.PENDING: frozenset({S.APPROVED, S.REJECTED, S.EXPIRED}),
    S.APPROVED: frozenset({S.REVOKED, S.FINISHED, S.EXPIRED}),
    S.REJECTED: frozenset(),
    S.EXPIRED: frozenset(),
    S.REVOKED: frozenset(),
    S.FINISHED: frozenset(),
}

_LOAD = (
    selectinload(AuthorizationRequest.engineer),
    selectinload(AuthorizationRequest.card),
    selectinload(AuthorizationRequest.area),
    selectinload(AuthorizationRequest.reviewer),
    selectinload(AuthorizationRequest.creator),
    selectinload(AuthorizationRequest.closer),
)


# ----------------------------------------------------------------- queries
def get(db: Session, request_id: int) -> AuthorizationRequest:
    req = db.get(AuthorizationRequest, request_id, options=_LOAD, populate_existing=True)
    if req is None:
        raise not_found("REQUEST_NOT_FOUND", "Solicitud no encontrada")
    return req


def list_(
    db: Session,
    page: PageParams,
    *,
    status: RequestStatus | None = None,
    engineer_id: int | None = None,
    card_id: int | None = None,
    area_id: int | None = None,
    in_force_at: datetime | None = None,
    q: str | None = None,
) -> tuple[list[AuthorizationRequest], int]:
    stmt = select(AuthorizationRequest)
    if q:
        # Free-text search over engineer code/name, card UID and area code/name.
        stmt = (
            stmt.join(Engineer, Engineer.id == AuthorizationRequest.engineer_id)
            .join(RfidCard, RfidCard.id == AuthorizationRequest.card_id)
            .join(Area, Area.id == AuthorizationRequest.area_id)
            .where(or_(
                Engineer.engineer_id.icontains(q, autoescape=True),
                Engineer.full_name.icontains(q, autoescape=True),
                RfidCard.uid.icontains(q, autoescape=True),
                Area.code.icontains(q, autoescape=True),
                Area.name.icontains(q, autoescape=True),
            ))
        )
    if status:
        stmt = stmt.where(AuthorizationRequest.status == status)
    if engineer_id:
        stmt = stmt.where(AuthorizationRequest.engineer_id == engineer_id)
    if card_id:
        stmt = stmt.where(AuthorizationRequest.card_id == card_id)
    if area_id:
        stmt = stmt.where(AuthorizationRequest.area_id == area_id)
    if in_force_at:
        stmt = in_force_clause(stmt, in_force_at)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(
        stmt.options(*_LOAD).order_by(AuthorizationRequest.start_at.desc(), AuthorizationRequest.id.desc())
        .limit(page.limit).offset(page.offset)
    ).scalars().all()
    return list(rows), total


def stats(db: Session, at: datetime) -> RequestStats:
    rows = db.execute(
        select(AuthorizationRequest.status, func.count()).group_by(AuthorizationRequest.status)
    ).all()
    by_status = {st: 0 for st in S}
    by_status.update({st: n for st, n in rows})
    in_force = db.execute(
        select(func.count()).select_from(in_force_clause(select(AuthorizationRequest.id), at).subquery())
    ).scalar_one()
    return RequestStats(by_status=by_status, in_force=in_force, total=sum(by_status.values()))


def in_force_clause(stmt, at: datetime):
    """Fail-closed definition of *vigente*, enforced in SQL. Mirrors ``AuthorizationRequest.is_in_force``:
    APROBADA + open window + card ACTIVA, unlocked and still bound to the engineer + engineer ACTIVO.
    """
    return (
        stmt.join(RfidCard, RfidCard.id == AuthorizationRequest.card_id)
        .join(Engineer, Engineer.id == AuthorizationRequest.engineer_id)
        .where(
            AuthorizationRequest.status == S.APPROVED,
            AuthorizationRequest.start_at <= at,
            AuthorizationRequest.end_at > at,
            RfidCard.status == CardStatus.ACTIVE,
            RfidCard.engineer_id == AuthorizationRequest.engineer_id,
            or_(RfidCard.locked_until.is_(None), RfidCard.locked_until <= at),
            Engineer.status == EngineerStatus.ACTIVE,
        )
    )


def find_in_force(db: Session, card_id: int, area_id: int, at: datetime) -> AuthorizationRequest | None:
    """The single source of truth the access engine (F5) uses to decide on authorization.

    Returns None unless every condition of ``in_force_clause`` holds, so a caller that forgets to
    check the card or engineer still fails closed.
    """
    stmt = select(AuthorizationRequest).where(
        AuthorizationRequest.card_id == card_id, AuthorizationRequest.area_id == area_id
    )
    return db.execute(
        in_force_clause(stmt, at).order_by(AuthorizationRequest.end_at.desc()).limit(1)
    ).scalar_one_or_none()


# ----------------------------------------------------------------- validation
def _resolve_ids(db: Session, data: RequestCreate) -> tuple[int, int]:
    """Map the form identifiers (public engineer id "ENG-0001", RFID UID) to internal ids."""
    engineer_id = data.engineer_id
    if isinstance(engineer_id, str):
        public_id = engineer_id
        engineer_id = db.execute(
            select(Engineer.id).where(Engineer.engineer_id == public_id)
        ).scalar_one_or_none()
        if engineer_id is None:
            raise not_found("ENGINEER_NOT_FOUND", f"No existe ningún ingeniero con ID {public_id}")
    card_id = data.card_id
    if card_id is None:
        card_id = db.execute(select(RfidCard.id).where(RfidCard.uid == data.card_uid)).scalar_one_or_none()
        if card_id is None:
            raise not_found("CARD_NOT_FOUND", f"La tarjeta {data.card_uid} no está registrada")
    return engineer_id, card_id


def _forbid_self_review(db: Session, ctx: ActorCtx, req: AuthorizationRequest) -> None:
    if ctx.actor_type != ActorType.ADMIN or ctx.actor_id is None:
        return
    admin = db.get(Admin, ctx.actor_id)
    if admin is not None and admin.engineer_id is not None and admin.engineer_id == req.engineer_id:
        ctx.audit(db, "request.self_review_blocked", "authorization_request", req.id,
                  {"engineer_id": req.engineer_id})
        db.commit()  # keep the evidence even though the action is refused
        raise DomainError("SELF_AUTHORIZATION", "No puedes decidir sobre tu propia solicitud de acceso", 403)


def _validate_parties(db: Session, engineer_id: int, card_id: int, area_id: int) -> tuple[Engineer, RfidCard, Area]:
    eng = db.get(Engineer, engineer_id)
    if eng is None:
        raise not_found("ENGINEER_NOT_FOUND", "Ingeniero no encontrado")
    if eng.status != EngineerStatus.ACTIVE:
        raise DomainError("ENGINEER_NOT_ACTIVE", "El ingeniero no está activo", 409)
    card = db.get(RfidCard, card_id)
    if card is None:
        raise not_found("CARD_NOT_FOUND", "Tarjeta no encontrada")
    if card.engineer_id != eng.id:
        raise DomainError("CARD_NOT_LINKED", "La tarjeta no está vinculada a este ingeniero", 409)
    if card.status != CardStatus.ACTIVE:
        raise DomainError("CARD_NOT_ACTIVE", "La tarjeta no está activa", 409)
    area = db.get(Area, area_id)
    if area is None:
        raise not_found("AREA_NOT_FOUND", "Área no encontrada")
    return eng, card, area


def _check_overlap(db: Session, card_id: int, area_id: int, start: datetime, end: datetime,
                   statuses: tuple[RequestStatus, ...], exclude_id: int | None = None) -> None:
    stmt = select(AuthorizationRequest.id).where(
        AuthorizationRequest.card_id == card_id,
        AuthorizationRequest.area_id == area_id,
        AuthorizationRequest.status.in_(statuses),
        AuthorizationRequest.start_at < end,
        AuthorizationRequest.end_at > start,
    )
    if exclude_id is not None:
        stmt = stmt.where(AuthorizationRequest.id != exclude_id)
    clash = db.execute(stmt.limit(1)).scalar()
    if clash:
        raise DomainError("REQUEST_OVERLAP", f"Se solapa con la solicitud #{clash} para la misma tarjeta y área", 409)


# ----------------------------------------------------------------- transitions
def _transition(db: Session, ctx: ActorCtx, req: AuthorizationRequest, to: RequestStatus,
                notes: str | None = None, *, action: str) -> None:
    if to not in TRANSITIONS[req.status]:
        raise DomainError(
            "INVALID_TRANSITION", f"No se puede pasar de {req.status.value} a {to.value}", 409
        )
    old = req.status
    req.status = to
    by_admin = ctx.actor_id if ctx.actor_type == ActorType.ADMIN else None
    if to in (S.APPROVED, S.REJECTED):  # "Administrador que aprobó o rechazó"
        req.reviewed_by = by_admin
        req.reviewed_at = ctx.now
        req.review_notes = notes
    else:  # REVOKED / FINISHED / EXPIRED keep the reviewer intact
        req.closed_by = by_admin
        req.closed_at = ctx.now
        req.close_notes = notes
    ctx.audit(db, action, "authorization_request", req.id,
              {"from": old, "to": to, **({"notes": notes} if notes else {})})


def create(db: Session, ctx: ActorCtx, data: RequestCreate) -> AuthorizationRequest:
    s = get_settings()
    engineer_id, card_id = _resolve_ids(db, data)
    _validate_parties(db, engineer_id, card_id, data.area_id)
    start = data.start_at
    if start < ctx.now - timedelta(minutes=s.request_start_grace_minutes):
        raise DomainError("START_IN_PAST", "La fecha de inicio ya pasó", 422)
    if start > ctx.now + timedelta(days=s.request_max_days_ahead):
        raise DomainError("START_TOO_FAR", f"Máximo {s.request_max_days_ahead} días de antelación", 422)
    end = AuthorizationRequest.compute_end(start, data.duration_minutes)
    _check_overlap(db, card_id, data.area_id, start, end, OPEN_STATUSES)

    req = AuthorizationRequest(
        engineer_id=engineer_id, card_id=card_id, area_id=data.area_id, reason=data.reason,
        observations=data.observations,
        start_at=start, duration_minutes=data.duration_minutes, end_at=end, status=S.PENDING,
        created_by=ctx.actor_id if ctx.actor_type == ActorType.ADMIN else None,
    )
    db.add(req)
    db.flush()
    ctx.audit(db, "request.created", "authorization_request", req.id, {
        "engineer_id": engineer_id, "card_id": card_id, "area_id": data.area_id,
        "start_at": start.isoformat(), "end_at": end.isoformat(), "duration_minutes": data.duration_minutes,
    })
    db.commit()
    return get(db, req.id)


def approve(db: Session, ctx: ActorCtx, request_id: int, notes: str | None) -> AuthorizationRequest:
    req = get(db, request_id)
    _forbid_self_review(db, ctx, req)
    if req.status == S.PENDING and req.end_at <= ctx.now:
        _transition(db, ctx, req, S.EXPIRED, "Ventana vencida antes de la aprobación", action="request.expired")
        db.commit()
        raise DomainError("REQUEST_WINDOW_PASSED", "La ventana de la solicitud ya terminó; quedó EXPIRADA", 409)
    if req.status != S.PENDING:
        raise DomainError("INVALID_TRANSITION", f"No se puede aprobar una solicitud {req.status.value}", 409)
    # Re-validate: things may have changed since the request was filed.
    _validate_parties(db, req.engineer_id, req.card_id, req.area_id)
    _check_overlap(db, req.card_id, req.area_id, req.start_at, req.end_at, (S.APPROVED,), exclude_id=req.id)
    _transition(db, ctx, req, S.APPROVED, notes, action="request.approved")
    db.commit()
    return get(db, req.id)


def reject(db: Session, ctx: ActorCtx, request_id: int, notes: str) -> AuthorizationRequest:
    req = get(db, request_id)
    _forbid_self_review(db, ctx, req)
    _transition(db, ctx, req, S.REJECTED, notes, action="request.rejected")
    db.commit()
    return get(db, req.id)


def revoke(db: Session, ctx: ActorCtx, request_id: int, notes: str) -> AuthorizationRequest:
    req = get(db, request_id)
    _transition(db, ctx, req, S.REVOKED, notes, action="request.revoked")
    db.commit()
    return get(db, req.id)


def finalize(db: Session, ctx: ActorCtx, request_id: int, notes: str | None) -> AuthorizationRequest:
    req = get(db, request_id)
    _transition(db, ctx, req, S.FINISHED, notes, action="request.finalized")
    db.commit()
    return get(db, req.id)


def close_open_requests(db: Session, ctx: ActorCtx, *, engineer_id: int | None = None,
                        card_id: int | None = None, note: str) -> tuple[int, int]:
    """Revoke APROBADA and reject PENDIENTE requests of an engineer/card. Caller commits."""
    if engineer_id is None and card_id is None:
        raise ValueError("engineer_id or card_id required")
    stmt = select(AuthorizationRequest).where(AuthorizationRequest.status.in_(OPEN_STATUSES))
    if engineer_id is not None:
        stmt = stmt.where(AuthorizationRequest.engineer_id == engineer_id)
    if card_id is not None:
        stmt = stmt.where(AuthorizationRequest.card_id == card_id)
    revoked = rejected = 0
    for req in db.execute(stmt).scalars():
        if req.status == S.APPROVED:
            _transition(db, ctx, req, S.REVOKED, note, action="request.revoked")
            revoked += 1
        else:
            _transition(db, ctx, req, S.REJECTED, note, action="request.rejected")
            rejected += 1
    return revoked, rejected


def has_open_requests(db: Session, *, card_id: int) -> bool:
    return db.execute(
        select(AuthorizationRequest.id).where(
            AuthorizationRequest.card_id == card_id, AuthorizationRequest.status.in_(OPEN_STATUSES)
        ).limit(1)
    ).first() is not None


# ----------------------------------------------------------------- scheduler
def sweep(db: Session, ctx: ActorCtx | None = None) -> dict[str, int]:
    """Close requests whose window has ended. Idempotent; safe to run at any interval.

    The access engine never relies on this: it checks the window itself (``find_in_force``).
    """
    ctx = ctx or ActorCtx.system()
    counts = {"expired": 0, "finished": 0}
    stmt = select(AuthorizationRequest).where(
        AuthorizationRequest.status.in_(OPEN_STATUSES), AuthorizationRequest.end_at <= ctx.now
    )
    for req in db.execute(stmt).scalars():
        if req.status == S.APPROVED and req.use_count > 0:
            _transition(db, ctx, req, S.FINISHED, "Ventana finalizada", action="request.finished")
            counts["finished"] += 1
        else:
            note = "Ventana vencida sin uso" if req.status == S.APPROVED else "Ventana vencida sin revisión"
            _transition(db, ctx, req, S.EXPIRED, note, action="request.expired")
            counts["expired"] += 1
    db.commit()
    return counts
