"""Alerts and the append-only, hash-chained audit log."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DDL, ForeignKey, String, Text, event
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime, utcnow
from app.models._columns import enum_col
from app.models.enums import ActorType, AlertSeverity


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(40), index=True)
    severity: Mapped[AlertSeverity] = mapped_column(enum_col(AlertSeverity), index=True)
    message: Mapped[str] = mapped_column(String(500))
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"))
    engineer_id: Mapped[int | None] = mapped_column(ForeignKey("engineers.id"))
    session_id: Mapped[str | None] = mapped_column(ForeignKey("access_sessions.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    acknowledged_by: Mapped[int | None] = mapped_column(ForeignKey("admins.id"))
    acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    actor_type: Mapped[ActorType] = mapped_column(enum_col(ActorType))
    actor_id: Mapped[str | None] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(40))
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    correlation_id: Mapped[str | None] = mapped_column(String(32), index=True)
    prev_hash: Mapped[str] = mapped_column(String(64), unique=True)  # a fork fails on insert
    hash: Mapped[str] = mapped_column(String(64), unique=True)


# Append-only enforcement at the database level (SQLite). Mirrored in the Alembic migration.
AUDIT_TRIGGERS_SQL = [
    "CREATE TRIGGER IF NOT EXISTS audit_log_no_update BEFORE UPDATE ON audit_log "
    "BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS audit_log_no_delete BEFORE DELETE ON audit_log "
    "BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END",
]
AUDIT_TRIGGERS_DROP_SQL = [
    "DROP TRIGGER IF EXISTS audit_log_no_update",
    "DROP TRIGGER IF EXISTS audit_log_no_delete",
]

for _sql in AUDIT_TRIGGERS_SQL:
    event.listen(AuditLog.__table__, "after_create", DDL(_sql).execute_if(dialect="sqlite"))
