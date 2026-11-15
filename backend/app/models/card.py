from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import UTCDateTime, utcnow
from app.models._columns import enum_col
from app.models.enums import CardStatus


def normalize_uid(uid: str) -> str:
    """Uppercase hex without separators, e.g. ``04:a1:b2:c3`` → ``04A1B2C3``."""
    cleaned = "".join(ch for ch in uid if ch not in " :-").upper()
    if not cleaned or len(cleaned) > 20 or any(ch not in "0123456789ABCDEF" for ch in cleaned):
        raise ValueError("Invalid RFID UID")
    return cleaned


class RfidCard(Base):
    __tablename__ = "rfid_cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    uid: Mapped[str] = mapped_column(String(20), unique=True)
    engineer_id: Mapped[int | None] = mapped_column(
        ForeignKey("engineers.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[CardStatus] = mapped_column(enum_col(CardStatus), default=CardStatus.ACTIVE)
    label: Mapped[str | None] = mapped_column(String(60))
    assigned_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    engineer: Mapped["Engineer | None"] = relationship(back_populates="cards")  # noqa: F821
