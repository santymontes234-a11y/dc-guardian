from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime, utcnow
from app.models._columns import enum_col
from app.models.enums import AccessDirection, AccessState


class AccessSession(Base):
    """One door attempt, from card read to door closed (or denial)."""

    __tablename__ = "access_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), index=True)
    direction: Mapped[AccessDirection] = mapped_column(
        enum_col(AccessDirection), default=AccessDirection.ENTRY
    )
    card_uid_raw: Mapped[str] = mapped_column(String(40))
    card_id: Mapped[int | None] = mapped_column(ForeignKey("rfid_cards.id"), index=True)
    engineer_id: Mapped[int | None] = mapped_column(ForeignKey("engineers.id"), index=True)
    request_id: Mapped[int | None] = mapped_column(ForeignKey("authorization_requests.id"))
    state: Mapped[AccessState] = mapped_column(enum_col(AccessState), default=AccessState.CARD_READ, index=True)
    reason_code: Mapped[str | None] = mapped_column(String(40))
    face_score: Mapped[float | None] = mapped_column(Float)
    presence_cm_start: Mapped[float | None] = mapped_column(Float)
    presence_cm_final: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    opened_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
