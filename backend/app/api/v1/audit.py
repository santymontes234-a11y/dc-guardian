import json
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select

from app.api.deps import AdminOrAuditor, ReadDb
from app.models import AuditLog
from app.models.enums import ActorType
from app.schemas.common import Page, PageParams, SaneDatetime, page_params
from app.services import audit

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: datetime
    actor_type: ActorType
    actor_id: str | None
    action: str
    entity: str | None
    entity_id: str | None
    details: dict[str, Any] = Field(validation_alias="details_json")
    correlation_id: str | None
    hash: str

    @field_validator("details", mode="before")
    @classmethod
    def _parse(cls, v):
        return json.loads(v) if isinstance(v, str) else v


@router.get("", response_model=Page[AuditOut])
def list_audit(
    _: AdminOrAuditor,
    db: ReadDb,
    page: Annotated[PageParams, Depends(page_params)],
    action: Annotated[str | None, Query(max_length=60)] = None,
    entity: Annotated[str | None, Query(max_length=40)] = None,
    entity_id: Annotated[str | None, Query(max_length=40)] = None,
    actor_type: ActorType | None = None,
    actor_id: Annotated[str | None, Query(max_length=40)] = None,
    correlation_id: Annotated[str | None, Query(max_length=32)] = None,
    since: SaneDatetime | None = None,
    until: SaneDatetime | None = None,
):
    """Newest first. ``action`` accepts a prefix ending in ``.`` (e.g. ``request.``)."""
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action.startswith(action, autoescape=True) if action.endswith(".")
                          else AuditLog.action == action)
    for col, val in ((AuditLog.entity, entity), (AuditLog.entity_id, entity_id), (AuditLog.actor_type, actor_type),
                     (AuditLog.actor_id, actor_id), (AuditLog.correlation_id, correlation_id)):
        if val is not None:
            stmt = stmt.where(col == val)
    if since:
        stmt = stmt.where(AuditLog.ts >= since)
    if until:
        stmt = stmt.where(AuditLog.ts < until)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(AuditLog.id.desc()).limit(page.limit).offset(page.offset)).scalars().all()
    return Page(items=[AuditOut.model_validate(r, from_attributes=True) for r in rows], total=total,
                limit=page.limit, offset=page.offset)


@router.get("/verify")
def verify_audit(_: AdminOrAuditor, db: ReadDb):
    """Recomputes the keyed hash chain. Note ``head_id``/``head_hash``: if a later check shows a
    smaller head, the tail of the log was truncated."""
    report = audit.verify_chain(db)
    return {
        "ok": report.ok,
        "checked": report.checked,
        "broken_at_id": report.broken_at_id,
        "head_id": report.head_id,
        "head_hash": report.head_hash,
    }
