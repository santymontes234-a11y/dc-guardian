"""Main entrance (reception): QR credentials and the log of QR scans with their LED signal.

A QR credential identifies an engineer (like an RFID card) but **never grants access by
itself**: every scan also requires an APROBADA authorization in force (Registro 2).
Only ``sha256(token)`` is stored; the full QR text is shown once, when issued.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import UTCDateTime, utcnow
from app.models._columns import enum_col
from app.models.enums import EntranceSignalStatus, QrStatus


class QrCredential(Base):
    __tablename__ = "qr_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    engineer_id: Mapped[int] = mapped_column(ForeignKey("engineers.id"), index=True)
    token_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    prefix: Mapped[str] = mapped_column(String(6))  # first 6 chars of the token, for display only
    status: Mapped[QrStatus] = mapped_column(enum_col(QrStatus), default=QrStatus.ACTIVE, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)  # NULL = does not expire
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("admins.id"))
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    revoked_by: Mapped[int | None] = mapped_column(ForeignKey("admins.id"))

    engineer = relationship("Engineer")


class EntranceEvent(Base):
    """One QR scan at the main entrance (bitácora row) and the one-shot signal it queued for
    the entrance device. ``id`` is also the signal id sent to the ESP32 (32 lowercase hex)."""

    __tablename__ = "entrance_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    area_id: Mapped[int | None] = mapped_column(ForeignKey("areas.id"))
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"), index=True)
    engineer_id: Mapped[int | None] = mapped_column(ForeignKey("engineers.id"), index=True)
    qr_credential_id: Mapped[int | None] = mapped_column(ForeignKey("qr_credentials.id"))
    request_id: Mapped[int | None] = mapped_column(ForeignKey("authorization_requests.id"))
    method: Mapped[str] = mapped_column(String(20), default="QR")
    result: Mapped[str] = mapped_column(String(10))  # GRANTED | DENIED
    reason_code: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    signal_status: Mapped[EntranceSignalStatus] = mapped_column(
        enum_col(EntranceSignalStatus), default=EntranceSignalStatus.PENDING, index=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    acked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
