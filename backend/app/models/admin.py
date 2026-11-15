from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime, utcnow
from app.models._columns import enum_col
from app.models.enums import AdminRole


class Admin(Base):
    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    full_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[AdminRole] = mapped_column(enum_col(AdminRole), default=AdminRole.ADMIN)
    # Optional link to the admin's own engineer record: an admin can never approve or reject
    # requests of the engineer they are ("ningún ingeniero puede autorizarse a sí mismo").
    engineer_id: Mapped[int | None] = mapped_column(
        ForeignKey("engineers.id", ondelete="SET NULL"), unique=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Incremented to invalidate every outstanding JWT (logout-all, password change, disable).
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
