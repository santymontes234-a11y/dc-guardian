"""Areas of the data center and the door devices (ESP32) that protect them."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import UTCDateTime, utcnow
from app.models._columns import enum_col
from app.models.enums import DeviceStatus


class Area(Base):
    __tablename__ = "areas"
    __table_args__ = (CheckConstraint("security_level BETWEEN 1 AND 5", name="security_level_range"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    security_level: Mapped[int] = mapped_column(Integer, default=3)
    description: Mapped[str | None] = mapped_column(Text)

    devices: Mapped[list[Device]] = relationship(back_populates="area")


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (
        CheckConstraint("presence_threshold_cm BETWEEN 2 AND 400", name="presence_range"),
        CheckConstraint("door_open_ms BETWEEN 1000 AND 30000", name="door_open_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    device_code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    area_id: Mapped[int] = mapped_column(ForeignKey("areas.id"), index=True)
    # HMAC needs the raw secret on the server, so it is encrypted (Fernet), not hashed.
    secret_encrypted: Mapped[str] = mapped_column(String(255))
    presence_threshold_cm: Mapped[int] = mapped_column(Integer, default=50)
    door_open_ms: Mapped[int] = mapped_column(Integer, default=5000)
    status: Mapped[DeviceStatus] = mapped_column(enum_col(DeviceStatus), default=DeviceStatus.OFFLINE)
    firmware_version: Mapped[str | None] = mapped_column(String(20))
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # Last heartbeat telemetry (JSON: door, distance, rssi, sensors...). Display only, never trusted.
    hw_status_json: Mapped[str | None] = mapped_column(Text)
    # One-shot command delivered in the next heartbeat response (only "EMERGENCY_CLOSE").
    pending_command: Mapped[str | None] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    area: Mapped[Area] = relationship(back_populates="devices")


class DeviceNonce(Base):
    """Anti-replay store; rows older than the clock-skew window can be purged."""

    __tablename__ = "device_nonces"

    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True)
    nonce: Mapped[str] = mapped_column(String(64), primary_key=True)
    seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
