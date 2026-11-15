"""Monitoring: access sessions, alerts, hardware status and dashboard metrics (read mostly)."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import func, select

from app.api.deps import AdminCtx, AdminOnly, AdminOrAuditor, DbSession, ReadDb
from app.api.v1.kiosk import kiosk_token
from app.db.types import utcnow
from app.models import AccessSession, Alert, Device, Engineer
from app.models.enums import AccessDirection, AccessState, AlertSeverity
from app.schemas.common import Page, PageParams, PathId, QueryId, SaneDatetime, page_params
from app.services import access_engine as engine
from app.services import alerts as alerts_service
from app.services import requests as requests_service

sessions = APIRouter(prefix="/access-sessions", tags=["access sessions"])
alerts = APIRouter(prefix="/alerts", tags=["alerts"])
stats = APIRouter(prefix="/stats", tags=["dashboard"])
hardware = APIRouter(prefix="/devices", tags=["devices"])
system = APIRouter(prefix="/system", tags=["system"])


# ------------------------------------------------------------------ access sessions
@sessions.get("", response_model=Page[dict])
def list_sessions(
    _: AdminOrAuditor,
    db: ReadDb,
    page: Annotated[PageParams, Depends(page_params)],
    state: AccessState | None = None,
    direction: AccessDirection | None = None,
    device_id: QueryId = None,
    engineer_id: QueryId = None,
    reason_code: Annotated[str | None, Query(max_length=40)] = None,
    since: SaneDatetime | None = None,
):
    stmt = select(AccessSession)
    for col, val in ((AccessSession.state, state), (AccessSession.direction, direction),
                     (AccessSession.device_id, device_id), (AccessSession.engineer_id, engineer_id),
                     (AccessSession.reason_code, reason_code)):
        if val is not None:
            stmt = stmt.where(col == val)
    if since:
        stmt = stmt.where(AccessSession.created_at >= since)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(AccessSession.created_at.desc()).limit(page.limit).offset(page.offset)).scalars()
    return Page(items=[engine.session_dict(r, db) for r in rows], total=total, limit=page.limit, offset=page.offset)


@sessions.get("/{session_id}")
def get_session(session_id: Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")], _: AdminOrAuditor, db: ReadDb):
    return engine.session_dict(engine.get_session(db, session_id), db)


# ------------------------------------------------------------------ alerts
@alerts.get("", response_model=Page[dict])
def list_alerts(
    _: AdminOrAuditor,
    db: ReadDb,
    page: Annotated[PageParams, Depends(page_params)],
    unacknowledged: bool = False,
    severity: AlertSeverity | None = None,
    type: Annotated[str | None, Query(max_length=40)] = None,  # noqa: A002
):
    items, total = alerts_service.list_(db, page, unacknowledged=unacknowledged, severity=severity, type_=type)
    return Page(items=[alerts_service.to_dict(a) for a in items], total=total, limit=page.limit, offset=page.offset)


@alerts.post("/{alert_id}/ack")
def ack_alert(alert_id: PathId, ctx: AdminCtx, db: DbSession):
    return alerts_service.to_dict(alerts_service.acknowledge(db, ctx, alert_id))


# ------------------------------------------------------------------ hardware
@hardware.get("/status/all")
def hardware_status(_: AdminOrAuditor, db: ReadDb):
    """Live hardware view: status, last heartbeat telemetry and sensors of every door."""
    return [engine.device_status_dict(d) for d in db.execute(select(Device).order_by(Device.device_code)).scalars()]


@hardware.post("/{device_id}/emergency-close")
def emergency_close(device_id: PathId, ctx: AdminCtx, db: DbSession):
    """Queues ``EMERGENCY_CLOSE`` for the next heartbeat. There is no remote *open* command."""
    return engine.device_status_dict(engine.request_emergency_close(db, ctx, device_id))


# ------------------------------------------------------------------ system
@system.get("/kiosk-token")
def get_kiosk_token(_: AdminOnly):
    """Token for the face kiosk (X-Kiosk-Token). Admin only."""
    return {"token": kiosk_token()}


# ------------------------------------------------------------------ dashboard
@stats.get("/dashboard")
def dashboard(_: AdminOrAuditor, db: ReadDb):
    now = utcnow()
    day = now - timedelta(hours=24)

    eng_rows = db.execute(select(Engineer.status, func.count()).group_by(Engineer.status)).all()
    engineers = {str(st): n for st, n in eng_rows}

    def count(*where) -> int:
        return db.execute(select(func.count()).select_from(AccessSession).where(*where)).scalar_one()

    granted_states = (AccessState.GRANTED, AccessState.OPENED, AccessState.CLOSED)
    access = {
        "entries_24h": count(AccessSession.created_at >= day, AccessSession.direction == AccessDirection.ENTRY,
                             AccessSession.state.in_(granted_states)),
        "exits_24h": count(AccessSession.created_at >= day, AccessSession.direction == AccessDirection.EXIT,
                           AccessSession.state.in_(granted_states)),
        "denied_24h": count(AccessSession.created_at >= day, AccessSession.state == AccessState.DENIED),
        "timeouts_24h": count(AccessSession.created_at >= day, AccessSession.state == AccessState.TIMEOUT),
        "in_progress": count(AccessSession.state.in_(engine.PENDING_STATES), AccessSession.expires_at > now),
    }
    reasons = db.execute(
        select(AccessSession.reason_code, func.count()).where(
            AccessSession.created_at >= day, AccessSession.state == AccessState.DENIED
        ).group_by(AccessSession.reason_code).order_by(func.count().desc())
    ).all()
    denials_by_reason = [{"reason_code": r, "reason": engine.reason_text(r), "count": n} for r, n in reasons]

    open_alerts = db.execute(
        select(Alert.severity, func.count()).where(Alert.acknowledged_at.is_(None)).group_by(Alert.severity)
    ).all()

    inside = _engineers_inside(db, now)
    recent = db.execute(select(AccessSession).order_by(AccessSession.created_at.desc()).limit(15)).scalars()
    recent_denials = db.execute(
        select(AccessSession).where(AccessSession.state == AccessState.DENIED)
        .order_by(AccessSession.created_at.desc()).limit(10)
    ).scalars()
    latest_alerts = db.execute(select(Alert).order_by(Alert.id.desc()).limit(10)).scalars()
    req_stats = requests_service.stats(db, now)

    return {
        "generated_at": now.isoformat(),
        "engineers": {"by_status": engineers, "total": sum(engineers.values()), "inside": inside},
        "requests": req_stats.model_dump(mode="json"),
        "access": access,
        "denials_by_reason": denials_by_reason,
        "alerts": {"open_by_severity": {str(s): n for s, n in open_alerts},
                   "open_total": sum(n for _, n in open_alerts),
                   "latest": [alerts_service.to_dict(a) for a in latest_alerts]},
        "devices": [engine.device_status_dict(d) for d in db.execute(select(Device).order_by(Device.device_code)).scalars()],
        "recent_sessions": [engine.session_dict(s, db) for s in recent],
        "recent_denials": [engine.session_dict(s, db) for s in recent_denials],
    }


def _engineers_inside(db, now) -> list[dict]:
    """Engineers whose last completed door cycle was an ENTRADA within the exit window."""
    from app.core.config import get_settings

    since = now - timedelta(hours=get_settings().exit_window_hours)
    rows = db.execute(
        select(AccessSession).where(AccessSession.opened_at >= since, AccessSession.engineer_id.is_not(None))
        .order_by(AccessSession.opened_at)
    ).scalars().all()
    last: dict[int, AccessSession] = {}
    for r in rows:
        last[r.engineer_id] = r
    out = []
    for eng_id, sess in last.items():
        if sess.direction == AccessDirection.ENTRY:
            eng = db.get(Engineer, eng_id)
            out.append({"id": eng_id, "engineer_id": eng.engineer_id if eng else None,
                        "full_name": eng.full_name if eng else None, "since": sess.opened_at.isoformat(),
                        "session_id": sess.id})
    return out
