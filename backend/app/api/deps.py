"""Shared FastAPI dependencies: DB session, current admin, role guards."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import DomainError
from app.db.session import get_db, get_read_db
from app.models import Admin
from app.models.enums import ActorType, AdminRole
from app.services.auth import admin_from_token
from app.services.context import ActorCtx

DbSession = Annotated[Session, Depends(get_db)]  # write session (BEGIN IMMEDIATE)
ReadDb = Annotated[Session, Depends(get_read_db)]  # read-only snapshot, never blocks writers


def _extract_token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(get_settings().cookie_name)


def get_current_admin(request: Request, db: ReadDb) -> Admin:
    token = _extract_token(request)
    if not token:
        raise DomainError("UNAUTHENTICATED", "Autenticación requerida", 401)
    admin = admin_from_token(db, token)
    request.state.admin_id = admin.id
    return admin


CurrentAdmin = Annotated[Admin, Depends(get_current_admin)]


def require_roles(*roles: AdminRole) -> Callable[[Admin], Admin]:
    def _guard(admin: CurrentAdmin) -> Admin:
        if admin.role not in roles:
            raise DomainError("FORBIDDEN", "Permisos insuficientes", 403)
        return admin

    return _guard


AdminOnly = Annotated[Admin, Depends(require_roles(AdminRole.ADMIN))]
AdminOrAuditor = Annotated[Admin, Depends(require_roles(AdminRole.ADMIN, AdminRole.AUDITOR))]


def admin_ctx(request: Request, admin: AdminOnly) -> ActorCtx:
    """Context for write operations (admin role only)."""
    return ActorCtx(ActorType.ADMIN, admin.id, request.state.correlation_id)


AdminCtx = Annotated[ActorCtx, Depends(admin_ctx)]
