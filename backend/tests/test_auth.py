import threading
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import DomainError
from app.db.session import SessionLocal
from app.db.types import utcnow
from app.models import Admin, AuditLog
from app.models.enums import AdminRole
from app.services import audit
from app.services import auth as auth_service
from tests.conftest import ADMIN_PASSWORD


def _login(client, username="admin", password=ADMIN_PASSWORD):
    return client.post("/api/v1/auth/login", json={"username": username, "password": password})


def test_login_sets_httponly_cookie_and_me_works(client, admin):
    r = _login(client)
    assert r.status_code == 200, r.text
    assert r.json()["admin"]["username"] == "admin"
    set_cookie = r.headers["set-cookie"].lower()
    assert "httponly" in set_cookie and "samesite=strict" in set_cookie
    assert "password" not in r.text

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["role"] == "admin"


def test_login_is_case_insensitive_on_username(client, admin):
    assert _login(client, username="  ADMIN ").status_code == 200


def test_wrong_password_and_unknown_user_look_identical(client, admin):
    r1 = _login(client, password="incorrecta-123")
    r2 = _login(client, username="nadie")
    assert r1.status_code == r2.status_code == 401
    assert r1.json()["error"]["code"] == r2.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert r1.json()["error"]["message"] == r2.json()["error"]["message"]


def test_lockout_after_max_failures(client, admin, db):
    for _ in range(get_settings().login_max_failures):
        assert _login(client, password="incorrecta-123").status_code == 401
    r = _login(client)  # even the correct password is refused while locked...
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_CREDENTIALS"  # ...with the generic answer

    db.expire_all()
    a = db.get(Admin, admin.id)
    assert a.locked_until is not None
    a.locked_until = utcnow() - timedelta(seconds=1)
    db.commit()
    assert _login(client).status_code == 200


def test_locked_and_unknown_accounts_are_indistinguishable(client, admin):
    real = [_login(client, password="incorrecta-123").json() for _ in range(6)]
    ghost = [_login(client, username="fantasma", password="incorrecta-123").json() for _ in range(4)]
    codes = {r["error"]["code"] for r in real + ghost}
    assert codes == {"INVALID_CREDENTIALS"}


def test_parallel_wrong_passwords_cannot_bypass_lockout(admin):
    """Regression: concurrent guesses used to overwrite each other's failure counter."""
    results = []

    def worker():
        with SessionLocal() as s:
            try:
                auth_service.login(s, "admin", "incorrecta-123")
            except DomainError as exc:
                results.append(exc.code)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results == ["INVALID_CREDENTIALS"] * 20

    with SessionLocal() as s:
        a = s.get(Admin, admin.id)
        assert a.locked_until is not None and a.locked_until > utcnow()
        fails = s.execute(
            select(AuditLog.details_json).where(AuditLog.action == "auth.login_failed")
        ).scalars().all()
        assert len(fails) == 20
        assert sum('"locked_until"' in d for d in fails) >= 1
        assert audit.verify_chain(s).ok
    # And the correct password is now refused.
    with SessionLocal() as s, pytest.raises(DomainError):
        auth_service.login(s, "admin", ADMIN_PASSWORD)


def test_login_rate_limited_per_ip(client):
    limit = get_settings().login_rate_per_minute
    codes = [_login(client, username="fantasma").status_code for _ in range(limit + 1)]
    assert codes[:limit] == [401] * limit
    assert codes[-1] == 429


def test_unknown_username_value_is_not_stored_in_audit(client, db):
    secretish = "MiClaveSecreta-por-error"
    _login(client, username=secretish)
    details = db.execute(select(AuditLog.details_json)).scalars().all()
    assert all(secretish.lower() not in d.lower() for d in details)


@pytest.mark.parametrize(
    "username,password,code",
    [
        ("ab", "contraseña-larga", "INVALID_USERNAME"),
        ("con espacio", "contraseña-larga", "INVALID_USERNAME"),
        ("x" * 51, "contraseña-larga", "INVALID_USERNAME"),
        ("valido", "corta", "WEAK_PASSWORD"),
        ("valido", "ñ" * 40, "WEAK_PASSWORD"),  # 80 bytes > bcrypt's 72
    ],
)
def test_create_admin_validation(db, username, password, code):
    with pytest.raises(DomainError) as exc:
        auth_service.create_admin(db, username, password, "Nombre", AdminRole.ADMIN)
    assert exc.value.code == code


def test_me_requires_auth(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHENTICATED"
    assert r.json()["error"]["correlation_id"]


def test_tampered_token_rejected(client, admin):
    token = _login(client).cookies.get(get_settings().cookie_name)
    client.cookies.clear()
    bad = token[:-2] + ("aa" if not token.endswith("aa") else "bb")
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {bad}"}).status_code == 401


def test_logout_invalidates_token(client, admin):
    token = _login(client).cookies.get(get_settings().cookie_name)
    assert client.post("/api/v1/auth/logout").status_code == 204
    client.cookies.clear()
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_disabled_admin_token_rejected(client, admin, db):
    _login(client)
    a = db.get(Admin, admin.id)
    a.is_active = False
    db.commit()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_auditor_can_verify_audit_chain(client, auditor):
    _login(client, username="auditor")
    r = client.get("/api/v1/audit/verify")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_login_events_are_audited(client, admin, db):
    _login(client, password="incorrecta-123")
    _login(client)
    actions = db.execute(select(AuditLog.action).order_by(AuditLog.id)).scalars().all()
    assert actions[-2:] == ["auth.login_failed", "auth.login"]


def test_security_headers_and_correlation_id(client):
    r = client.get("/api/v1/health", headers={"X-Correlation-Id": "demo-1234"})
    assert r.status_code == 200
    assert r.headers["x-correlation-id"] == "demo-1234"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "no-store"
