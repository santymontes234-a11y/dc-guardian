"""REGISTRO 2 — temporary access authorization request, bound to engineer + RFID card + area."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import UTCDateTime, utcnow
from app.models._columns import enum_col
from app.models.enums import RequestStatus


class AuthorizationRequest(Base):
    __tablename__ = "authorization_requests"
    __table_args__ = (
        CheckConstraint("duration_minutes BETWEEN 1 AND 1440", name="duration_range"),
        CheckConstraint("end_at > start_at", name="window_order"),
        Index("ix_authreq_lookup", "card_id", "status", "start_at", "end_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    engineer_id: Mapped[int] = mapped_column(ForeignKey("engineers.id"), index=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("rfid_cards.id"))
    area_id: Mapped[int] = mapped_column(ForeignKey("areas.id"))
    reason: Mapped[str] = mapped_column(Text)
    observations: Mapped[str | None] = mapped_column(Text)  # "Observaciones" (optional, free text)
    start_at: Mapped[datetime] = mapped_column(UTCDateTime)  # fecha + hora
    duration_minutes: Mapped[int] = mapped_column(Integer)
    end_at: Mapped[datetime] = mapped_column(UTCDateTime)
    status: Mapped[RequestStatus] = mapped_column(
        enum_col(RequestStatus), default=RequestStatus.PENDING, index=True
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("admins.id"))
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("admins.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    review_notes: Mapped[str | None] = mapped_column(String(500))
    # Closing (revoked / finished / expired) is tracked separately so the approver is never lost.
    closed_by: Mapped[int | None] = mapped_column(ForeignKey("admins.id"))  # NULL = system
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    close_notes: Mapped[str | None] = mapped_column(String(500))
    first_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    use_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    engineer = relationship("Engineer")
    card = relationship("RfidCard")
    area = relationship("Area")
    reviewer = relationship("Admin", foreign_keys=[reviewed_by])
    creator = relationship("Admin", foreign_keys=[created_by])
    closer = relationship("Admin", foreign_keys=[closed_by])

    @staticmethod
    def compute_end(start_at: datetime, duration_minutes: int) -> datetime:
        return start_at + timedelta(minutes=duration_minutes)

    def window_open(self, at: datetime) -> bool:
        """APROBADA and ``at`` within [start_at, end_at) — the request alone, nothing else."""
        return self.status == RequestStatus.APPROVED and self.start_at <= at < self.end_at

    def is_in_force(self, at: datetime) -> bool:
        """Vigente (fail-closed): open window AND the card is ACTIVA, not locked and still bound
        to this engineer AND the engineer is ACTIVO. Mirrors ``services.requests.in_force_clause``."""
        from app.models.enums import CardStatus, EngineerStatus

        card, eng = self.card, self.engineer
        return (
            self.window_open(at)
            and card is not None
            and card.status == CardStatus.ACTIVE
            and card.engineer_id == self.engineer_id
            and (card.locked_until is None or card.locked_until <= at)
            and eng is not None
            and eng.status == EngineerStatus.ACTIVE
        )

    @property
    def in_force(self) -> bool:
        return self.is_in_force(utcnow())
