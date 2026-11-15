"""Administrator authentication: login with lockout, token validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

import jwt
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import DomainError
from app.core.security import (
    MAX_PASSWORD_BYTES,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.db.types import utcnow
from app.models import Admin
from app.models.enums import ActorType, AdminRole
from app.services import audit

USERNAME_RE = re.compile(r"^[a-z0-9._-]{3,50}$")
MIN_PASSWORD_LEN = 10


def _invalid_credentials() -> DomainError:
    # Same response for: unknown user, wrong password, disabled or locked account.
    return DomainError("INVALID_CREDENTIALS", "Usuario o contraseña incorrectos", 401)


def normalize_username(username: str) -> str:
    return username.strip().lower()


def create_admin(db: Session, username: str, password: str, full_name: str, role: AdminRole,
                 engineer_id: int | None = None) -> Admin:
    """``engineer_id`` links the admin to their own engineer record (if they also work in the
    Data Center), so they can never approve or reject their own access requests."""
    username = normalize_username(username)
    if not USERNAME_RE.fullmatch(username):
        raise DomainError("INVALID_USERNAME", "Usuario inválido: 3–50 caracteres [a-z 0-9 . _ -]", 422)
    if len(password) < MIN_PASSWORD_LEN or len(password.encode()) > MAX_PASSWORD_BYTES:
        raise DomainError(
            "WEAK_PASSWORD", f"La contraseña debe tener entre {MIN_PASSWORD_LEN} y {MAX_PASSWORD_BYTES} bytes", 422
        )
    if db.execute(select(Admin.id).where(Admin.username == username)).scalar_one_or_none():
        raise DomainError("ADMIN_EXISTS", "El usuario ya existe", 409)
    if engineer_id is not None:
        from app.models import Engineer

        if db.get(Engineer, engineer_id) is None:
            raise DomainError("ENGINEER_NOT_FOUND", "Ingeniero no encontrado", 404)
        if db.execute(select(Admin.id).where(Admin.engineer_id == engineer_id)).scalar_one_or_none():
            raise DomainError("ENGINEER_ALREADY_LINKED", "Ese ingeniero ya está vinculado a otro administrador", 409)
    admin = Admin(username=username, password_hash=hash_password(password), full_name=full_name.strip()[:120],
                  role=role, engineer_id=engineer_id)
    db.add(admin)
    db.flush()
    audit.record(db, action="admin.created", actor_type=ActorType.SYSTEM, entity="admin", entity_id=admin.id,
                 details={"username": username, "role": str(role), "engineer_id": engineer_id})
    return admin


@dataclass
class LoginResult:
    admin: Admin
    token: str
    expires_at: datetime


def login(db: Session, username: str, password: str, correlation_id: str | None = None) -> LoginResult:
    """Authenticate an admin.

    The slow bcrypt check runs *outside* any DB transaction; the counters are then updated in a
    short write-locked transaction with an atomic increment, so parallel guesses cannot race the
    lockout.
    """
    s = get_settings()
    uname = normalize_username(username)

    # 1) Short read to fetch the hash, then release the transaction.
    row = db.execute(select(Admin.id, Admin.password_hash).where(Admin.username == uname)).first()
    db.rollback()

    # 2) Constant-ish time password check without holding locks.
    password_ok = verify_password(password, row.password_hash if row else None)

    # 3) Authoritative decision under the write lock.
    now = utcnow()
    if row is None:
        audit.record(db, action="auth.login_failed", actor_type=ActorType.SYSTEM,
                     details={"reason": "unknown_user", "username_len": len(username)},
                     correlation_id=correlation_id)
        db.commit()
        raise _invalid_credentials()

    admin = db.get(Admin, row.id, populate_existing=True)
    locked = admin.locked_until is not None and admin.locked_until > now

    if locked or not admin.is_active or not password_ok:
        details: dict = {}
        if locked:
            details["reason"] = "locked"
        elif not admin.is_active:
            details["reason"] = "inactive"
        else:
            details["reason"] = "bad_password"
            failures = db.execute(
                update(Admin).where(Admin.id == admin.id)
                .values(failed_logins=Admin.failed_logins + 1)
                .returning(Admin.failed_logins)
            ).scalar_one()
            details["failed_logins"] = failures
            if failures >= s.login_max_failures:
                until = now + timedelta(minutes=s.login_lockout_minutes)
                db.execute(update(Admin).where(Admin.id == admin.id).values(failed_logins=0, locked_until=until))
                details["locked_until"] = until.isoformat()
        audit.record(db, action="auth.login_failed", actor_type=ActorType.ADMIN, actor_id=admin.id,
                     details=details, correlation_id=correlation_id)
        db.commit()
        raise _invalid_credentials()

    admin.failed_logins = 0
    admin.locked_until = None
    admin.last_login_at = now
    token, exp = create_access_token(str(admin.id), str(admin.role), admin.token_version)
    audit.record(db, action="auth.login", actor_type=ActorType.ADMIN, actor_id=admin.id,
                 correlation_id=correlation_id)
    db.commit()
    return LoginResult(admin, token, exp)


def logout(db: Session, admin: Admin, correlation_id: str | None = None) -> None:
    """Invalidate every token of this admin (bump token_version)."""
    db.execute(update(Admin).where(Admin.id == admin.id).values(token_version=Admin.token_version + 1))
    audit.record(db, action="auth.logout", actor_type=ActorType.ADMIN, actor_id=admin.id,
                 correlation_id=correlation_id)
    db.commit()


def admin_from_token(db: Session, token: str) -> Admin:
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        raise DomainError("UNAUTHENTICATED", "Sesión inválida o expirada", 401) from None
    sub = str(payload["sub"])
    admin = db.get(Admin, int(sub)) if sub.isdigit() else None
    if admin is None or not admin.is_active or admin.token_version != payload["tv"]:
        raise DomainError("UNAUTHENTICATED", "Sesión inválida o expirada", 401)
    return admin
