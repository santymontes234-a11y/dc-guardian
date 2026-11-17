"""Server-room environment readings (DHT11 on the door ESP32). Purged after 7 days."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime, utcnow
from app.models._columns import enum_col
from app.models.enums import SensorReading


class EnvironmentReading(Base):
    __tablename__ = "environment_readings"
    __table_args__ = (Index("ix_envreading_device_at", "device_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    area_id: Mapped[int | None] = mapped_column(ForeignKey("areas.id"))
    temperature_c: Mapped[float | None] = mapped_column(Float)
    humidity_pct: Mapped[float | None] = mapped_column(Float)
    sensor: Mapped[SensorReading] = mapped_column(enum_col(SensorReading, 10))
    fan: Mapped[bool] = mapped_column(Boolean, default=False)
    alarm: Mapped[bool] = mapped_column(Boolean, default=False)
    # Alert conditions active after this reading (comma separated, e.g. "TEMPERATURA_ALTA"):
    # an alert is raised only when its condition appears, and re-armed when it disappears.
    conditions: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
