from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.api.deps import AdminCtx, AdminOrAuditor, DbSession, ReadDb
from app.models.enums import CardStatus
from app.schemas.common import Page, PageParams, PathId, QueryId, page_params
from app.schemas.facility import CardAssign, CardCreate, CardOut, CardStatusChange, CardUpdate
from app.services import cards as svc

router = APIRouter(prefix="/cards", tags=["rfid cards"])


class CardStatusResult(BaseModel):
    card: CardOut
    requests_revoked: int
    requests_rejected: int


@router.get("", response_model=Page[CardOut])
def list_cards(
    _: AdminOrAuditor,
    db: ReadDb,
    page: Annotated[PageParams, Depends(page_params)],
    status: CardStatus | None = None,
    engineer_id: QueryId = None,
    unassigned: bool = False,
    q: Annotated[str | None, Query(max_length=40)] = None,
):
    items, total = svc.list_(db, page, status=status, engineer_id=engineer_id, unassigned=unassigned, q=q)
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@router.post("", response_model=CardOut, status_code=201)
def create_card(body: CardCreate, ctx: AdminCtx, db: DbSession):
    return svc.create(db, ctx, body)


@router.get("/{card_id}", response_model=CardOut)
def get_card(card_id: PathId, _: AdminOrAuditor, db: ReadDb):
    return svc.get(db, card_id)


@router.patch("/{card_id}", response_model=CardOut)
def update_card(card_id: PathId, body: CardUpdate, ctx: AdminCtx, db: DbSession):
    return svc.update_label(db, ctx, card_id, body.label)


@router.post("/{card_id}/assign", response_model=CardOut)
def assign_card(card_id: PathId, body: CardAssign, ctx: AdminCtx, db: DbSession):
    """Bind the card to an engineer (or unbind with ``engineer_id: null``)."""
    return svc.assign(db, ctx, card_id, body.engineer_id)


@router.post("/{card_id}/status", response_model=CardStatusResult)
def change_card_status(card_id: PathId, body: CardStatusChange, ctx: AdminCtx, db: DbSession):
    card, revoked, rejected = svc.change_status(db, ctx, card_id, body.status, body.reason)
    return CardStatusResult(card=card, requests_revoked=revoked, requests_rejected=rejected)


@router.post("/{card_id}/unlock", response_model=CardOut)
def unlock_card(card_id: PathId, ctx: AdminCtx, db: DbSession):
    return svc.unlock(db, ctx, card_id)
