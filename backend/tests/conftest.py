import os
import tempfile
from pathlib import Path

# Configure BEFORE importing the app (engine is created at import time).
_TMP = Path(tempfile.mkdtemp(prefix="dcg-test-"))
os.environ["DCG_ENV"] = "test"
os.environ["DCG_DATA_DIR"] = str(_TMP)
os.environ["DCG_DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from sqlalchemy import text  # noqa: E402

import app.models  # noqa: E402,F401
from app.api.v1.auth import login_limiter  # noqa: E402
from app.models.monitoring import AUDIT_TRIGGERS_DROP_SQL  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import ReadSessionLocal, SessionLocal, engine  # noqa: E402,F401
from app.main import app as fastapi_app  # noqa: E402
from app.models.enums import AdminRole  # noqa: E402
from app.services.auth import create_admin  # noqa: E402

ADMIN_PASSWORD = "Correcta-Horse-42"


@pytest.fixture(autouse=True)
def _fresh_schema():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    login_limiter.reset()
    yield


def _login_client(username: str) -> TestClient:
    c = TestClient(fastapi_app)
    r = c.post("/api/v1/auth/login", json={"username": username, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return c


@pytest.fixture
def api(admin):
    """TestClient logged in as an admin."""
    with _login_client("admin") as c:
        yield c


@pytest.fixture
def auditor_api(auditor):
    with _login_client("auditor") as c:
        yield c


class Factory:
    """Builds domain objects through the public API (so tests exercise the real rules)."""

    def __init__(self, client: TestClient):
        self.c = client
        self._n = 0

    def _next(self) -> int:
        self._n += 1
        return self._n

    def ok(self, method: str, url: str, expected: int = 200, **kw) -> dict:
        r = self.c.request(method, url, **kw)
        assert r.status_code == expected, f"{method} {url} -> {r.status_code}: {r.text}"
        return r.json() if r.content else {}

    def engineer(self, **over) -> dict:
        n = self._next()
        body = {"full_name": f"Ingeniero {n}", "department": "Infraestructura",
                "position": "Ingeniero", "institutional_email": f"ing{n}@dcguardian.edu", **over}
        return self.ok("POST", "/api/v1/engineers", 201, json=body)

    def card(self, engineer_id: int | None = None, uid: str | None = None) -> dict:
        uid = uid or f"{0xA0000000 + self._next():08X}"
        return self.ok("POST", "/api/v1/cards", 201, json={"uid": uid, "engineer_id": engineer_id})

    def area(self, code: str | None = None) -> dict:
        code = code or f"AREA-{self._next()}"
        return self.ok("POST", "/api/v1/areas", 201, json={"code": code, "name": f"Área {code}"})

    def request(self, engineer: dict, card: dict, area: dict, start=None, minutes: int = 60, expected=201,
                **over):
        from datetime import timedelta

        from app.db.types import utcnow

        start = start or (utcnow() + timedelta(minutes=10))
        body = {"engineer_id": engineer["id"], "card_id": card["id"], "area_id": area["id"],
                "reason": "Mantenimiento preventivo", "start_at": start.isoformat(), "duration_minutes": minutes,
                **over}
        r = self.c.post("/api/v1/requests", json=body)
        assert r.status_code == expected, r.text
        return r.json()

    def setup(self):
        """Active engineer + linked card + area."""
        eng = self.engineer()
        card = self.card(eng["id"])
        area = self.area()
        return eng, card, area


@pytest.fixture
def f(api) -> Factory:
    return Factory(api)


def drop_audit_triggers(db):
    """Simulate an attacker with raw DB access who first removes the append-only triggers."""
    for sql in AUDIT_TRIGGERS_DROP_SQL:
        db.execute(text(sql))
    db.commit()


@pytest.fixture
def db():
    # Deferred-BEGIN session: tests keep it open across API calls, and it must not hold
    # the write lock while the app (another connection) writes.
    with ReadSessionLocal() as session:
        yield session


@pytest.fixture
def client():
    with TestClient(fastapi_app) as c:
        yield c


@pytest.fixture
def admin(db):
    a = create_admin(db, "admin", ADMIN_PASSWORD, "Admin Pruebas", AdminRole.ADMIN)
    db.commit()
    return a


@pytest.fixture
def auditor(db):
    a = create_admin(db, "auditor", ADMIN_PASSWORD, "Auditor Pruebas", AdminRole.AUDITOR)
    db.commit()
    return a
