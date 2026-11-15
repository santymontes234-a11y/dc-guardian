"""Alerts for anomalous events (design doc §7). Created inside the caller's transaction."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import DomainError, not_found
from app.models import Alert
from app.models.enums import AlertSeverity
from app.schemas.common import PageParams
from app.services.context import ActorCtx
from app.ws.hub import defer

SEV = AlertSeverity

# type → default severity
ALERT_TYPES: dict[str, AlertSeverity] = {
    "UNKNOWN_CARD": SEV.WARN,
    "CARD_NOT_LINKED": SEV.WARN,
    "CARD_BLOCKED": SEV.WARN,
    "NO_VALID_AUTH": SEV.WARN,
    "NO_FACE_ENROLLED": SEV.WARN,
    "FACE_MISMATCH": SEV.WARN,
    "REPEATED_FAILURES": SEV.CRITICAL,
    "INACTIVE_ENGINEER": SEV.CRITICAL,
    "DEVICE_AUTH_FAIL": SEV.CRITICAL,
    "DEVICE_OFFLINE": SEV.WARN,
    "DEVICE_DISABLED": SEV.WARN,
    "SENSOR_FAULT": SEV.WARN,
    "PRESENCE_LOST": SEV.INFO,
    "DEVICE_EVENT": SEV.WARN,
    "EMERGENCY_CLOSE": SEV.WARN,
}


def to_dict(a: Alert) -> dict:
    return {
        "id": a.id, "type": a.type, "severity": str(a.severity), "message": a.message,
        "device_id": a.device_id, "engineer_id": a.engineer_id, "session_id": a.session_id,
        "created_at": a.created_at.isoformat(), "acknowledged_by": a.acknowledged_by,
        "acknowledged_at": a.acknowledged_at.isoformat() if a.acknowledged_at else None,
    }


def raise_alert(
    db: Session,
    ctx: ActorCtx,
    type_: str,
    message: str,
    *,
    severity: AlertSeverity | None = None,
    device_id: int | None = None,
    engineer_id: int | None = None,
    session_id: str | None = None,
    dedupe_s: int | None = None,
) -> Alert | None:
    """Create an alert (audited, pushed by WS after commit). ``dedupe_s`` suppresses repeats of
    the same type for the same device/engineer within that window (e.g. a flood of bad
    signatures). Returns None when suppressed. Caller commits."""
    if dedupe_s:
        since = ctx.now - timedelta(seconds=dedupe_s)
        dup = db.execute(
            select(Alert.id).where(
                Alert.type == type_, Alert.device_id.is_(device_id) if device_id is None else Alert.device_id == device_id,
                Alert.engineer_id.is_(engineer_id) if engineer_id is None else Alert.engineer_id == engineer_id,
                Alert.created_at >= since,
            ).limit(1)
        ).first()
        if dup:
            return None
    alert = Alert(
        type=type_, severity=severity or ALERT_TYPES.get(type_, SEV.WARN), message=message[:500],
        device_id=device_id, engineer_id=engineer_id, session_id=session_id, created_at=ctx.now,
    )
    db.add(alert)
    db.flush()
    ctx.audit(db, "alert.created", "alert", alert.id,
              {"type": type_, "severity": str(alert.severity), "session_id": session_id})
    defer(db, "alert.created", to_dict(alert))
    return alert


def list_(db: Session, page: PageParams, *, unacknowledged: bool = False,
          severity: AlertSeverity | None = None, type_: str | None = None) -> tuple[list[Alert], int]:
    stmt = select(Alert)
    if unacknowledged:
        stmt = stmt.where(Alert.acknowledged_at.is_(None))
    if severity:
        stmt = stmt.where(Alert.severity == severity)
    if type_:
        stmt = stmt.where(Alert.type == type_)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(Alert.id.desc()).limit(page.limit).offset(page.offset)).scalars().all()
    return list(rows), total


def acknowledge(db: Session, ctx: ActorCtx, alert_id: int) -> Alert:
    alert = db.get(Alert, alert_id, populate_existing=True)
    if alert is None:
        raise not_found("ALERT_NOT_FOUND", "Alerta no encontrada")
    if alert.acknowledged_at is not None:
        raise DomainError("ALERT_ALREADY_ACKNOWLEDGED", "La alerta ya fue atendida", 409)
    alert.acknowledged_by = ctx.actor_id
    alert.acknowledged_at = ctx.now
    ctx.audit(db, "alert.acknowledged", "alert", alert.id, {"type": alert.type})
    defer(db, "alert.acknowledged", to_dict(alert))
    db.commit()
    return alert
