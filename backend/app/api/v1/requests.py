from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import AdminCtx, AdminOrAuditor, DbSession, ReadDb
from app.db.types import utcnow
from app.models.enums import RequestStatus
from app.schemas.common import Page, PageParams, PathId, QueryId, page_params
from app.schemas.requests import RequestCreate, RequestOut, RequestStats, ReviewIn, ReviewRequiredIn
from app.services import requests as svc

router = APIRouter(prefix="/requests", tags=["authorization requests (Registro 2)"])


@router.get("", response_model=Page[RequestOut])
def list_requests(
    _: AdminOrAuditor,
    db: ReadDb,
    page: Annotated[PageParams, Depends(page_params)],
    status: RequestStatus | None = None,
    engineer_id: QueryId = None,
    card_id: QueryId = None,
    area_id: QueryId = None,
    in_force: bool = False,
    q: Annotated[str | None, Query(max_length=80)] = None,
):
    """Newest window first. ``q`` searches engineer code/name, card UID and area."""
    items, total = svc.list_(db, page, status=status, engineer_id=engineer_id, card_id=card_id,
                             area_id=area_id, in_force_at=utcnow() if in_force else None, q=q)
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@router.get("/stats", response_model=RequestStats)
def request_stats(_: AdminOrAuditor, db: ReadDb):
    return svc.stats(db, utcnow())


@router.post("", response_model=RequestOut, status_code=201)
def create_request(body: RequestCreate, ctx: AdminCtx, db: DbSession):
    """Creates a PENDIENTE request. The engineer must exist and be ACTIVO; the RFID card must be
    registered, ACTIVA and linked to that engineer. Creating a request never grants access."""
    return svc.create(db, ctx, body)


@router.get("/{request_id}", response_model=RequestOut)
def get_request(request_id: PathId, _: AdminOrAuditor, db: ReadDb):
    return svc.get(db, request_id)


@router.post("/{request_id}/approve", response_model=RequestOut)
def approve_request(request_id: PathId, body: ReviewIn, ctx: AdminCtx, db: DbSession):
    """Generates the temporary authorization (APROBADA) bound to the engineer and card. The
    approving admin is recorded; an admin cannot approve their own request (403)."""
    return svc.approve(db, ctx, request_id, body.notes)


@router.post("/{request_id}/reject", response_model=RequestOut)
def reject_request(request_id: PathId, body: ReviewRequiredIn, ctx: AdminCtx, db: DbSession):
    return svc.reject(db, ctx, request_id, body.notes)


@router.post("/{request_id}/revoke", response_model=RequestOut)
def revoke_request(request_id: PathId, body: ReviewRequiredIn, ctx: AdminCtx, db: DbSession):
    return svc.revoke(db, ctx, request_id, body.notes)


@router.post("/{request_id}/finalize", response_model=RequestOut)
def finalize_request(request_id: PathId, body: ReviewIn, ctx: AdminCtx, db: DbSession):
    return svc.finalize(db, ctx, request_id, body.notes)
