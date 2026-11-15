"""ACCESS AUTHORIZATION module (Registro 2): form identifiers, window input, separation of duties."""

from datetime import timedelta

from sqlalchemy import select

from app.db.types import utcnow
from app.models import Admin, AuditLog
from app.models.enums import AdminRole
from app.services.auth import create_admin
from tests.conftest import ADMIN_PASSWORD, _login_client

REQ = "/api/v1/requests"


def _form(eng, card, area, start=None, **over):
    start = start or (utcnow() + timedelta(minutes=30))
    return {"engineer_id": eng["engineer_id"], "card_uid": card["uid"], "area_id": area["id"],
            "reason": "Cambio de disco en rack 4", "start_at": start.isoformat(), **over}


# ----------------------------------------------------------------- form
def test_create_by_public_engineer_id_and_card_uid(f):
    eng, card, area = f.setup()
    start = utcnow() + timedelta(hours=1)
    body = _form(eng, card, area, start, end_at=(start + timedelta(minutes=90)).isoformat(),
                 observations="Acompañado por proveedor")
    r = f.ok("POST", REQ, 201, json=body)
    assert r["status"] == "PENDIENTE" and r["duration_minutes"] == 90
    assert r["engineer"]["engineer_id"] == eng["engineer_id"] and r["card"]["uid"] == card["uid"]
    assert r["observations"] == "Acompañado por proveedor"
    assert r["in_force"] is False  # a pending request never grants access


def test_uid_is_normalized(f):
    eng, card, area = f.setup()
    pretty = ":".join(card["uid"][i:i + 2] for i in range(0, len(card["uid"]), 2)).lower()
    f.ok("POST", REQ, 201, json=_form(eng, card, area, card_uid=pretty, duration_minutes=30))


def test_unknown_engineer_or_card(f):
    eng, card, area = f.setup()
    r = f.c.post(REQ, json=_form(eng, card, area, engineer_id="ENG-9999", duration_minutes=30))
    assert r.status_code == 404 and r.json()["error"]["code"] == "ENGINEER_NOT_FOUND"
    r = f.c.post(REQ, json=_form(eng, card, area, card_uid="FFFF0000", duration_minutes=30))
    assert r.status_code == 404 and r.json()["error"]["code"] == "CARD_NOT_FOUND"


def test_card_of_other_engineer_rejected(f):
    eng, _, area = f.setup()
    other = f.card(f.engineer()["id"])
    r = f.c.post(REQ, json=_form(eng, other, area, duration_minutes=30))
    assert r.status_code == 409 and r.json()["error"]["code"] == "CARD_NOT_LINKED"


def test_window_inputs(f):
    eng, card, area = f.setup()
    start = utcnow() + timedelta(hours=2)
    end = (start + timedelta(minutes=45)).isoformat()
    cases = [
        {},  # neither duration nor end
        {"end_at": end, "duration_minutes": 60},  # inconsistent
        {"end_at": start.isoformat()},  # end == start
        {"end_at": (start + timedelta(hours=25)).isoformat()},  # > 24 h
        {"card_id": card["id"], "duration_minutes": 30},  # card given twice
    ]
    for extra in cases:
        r = f.c.post(REQ, json=_form(eng, card, area, start, **extra))
        assert r.status_code == 422, (extra, r.text)
    ok = f.ok("POST", REQ, 201, json=_form(eng, card, area, start, end_at=end, duration_minutes=45))
    assert ok["end_at"].startswith((start + timedelta(minutes=45)).isoformat()[:16])


def test_suspended_engineer_cannot_request_or_be_approved(f):
    eng, card, area = f.setup()
    req = f.ok("POST", REQ, 201, json=_form(eng, card, area, duration_minutes=30))
    f.ok("POST", f"/api/v1/engineers/{eng['id']}/status", json={"status": "SUSPENDIDO", "reason": "Investigación"})
    # suspension rejects open requests automatically
    assert f.ok("GET", f"{REQ}/{req['id']}")["status"] == "RECHAZADA"
    r = f.c.post(REQ, json=_form(eng, card, area, duration_minutes=30))
    assert r.status_code == 409 and r.json()["error"]["code"] == "ENGINEER_NOT_ACTIVE"


def test_duplicate_rfid_card_rejected(f):
    eng = f.engineer()
    card = f.card(eng["id"])
    r = f.c.post("/api/v1/cards", json={"uid": card["uid"].lower(), "engineer_id": f.engineer()["id"]})
    assert r.status_code == 409


# ----------------------------------------------------------------- separation of duties
def _admin_linked_to(db, engineer_pk: int, username: str = "laura.admin") -> None:
    create_admin(db, username, ADMIN_PASSWORD, "Laura (admin)", AdminRole.ADMIN, engineer_id=engineer_pk)
    db.commit()


def test_admin_cannot_authorize_themselves(f, db):
    eng, card, area = f.setup()
    req = f.ok("POST", REQ, 201, json=_form(eng, card, area, duration_minutes=60))
    _admin_linked_to(db, eng["id"])
    with _login_client("laura.admin") as self_admin:
        for action, body in (("approve", {}), ("reject", {"notes": "No procede"})):
            r = self_admin.post(f"{REQ}/{req['id']}/{action}", json=body)
            assert r.status_code == 403 and r.json()["error"]["code"] == "SELF_AUTHORIZATION"
        # The attempt is audited; the request stays untouched.
        assert self_admin.get(f"{REQ}/{req['id']}").json()["status"] == "PENDIENTE"
    blocked = db.execute(select(AuditLog).where(AuditLog.action == "request.self_review_blocked")).scalars().all()
    assert len(blocked) == 2
    # Another admin can decide; the decision records who took it.
    out = f.ok("POST", f"{REQ}/{req['id']}/approve", json={"notes": "Aprobado por supervisor"})
    assert out["status"] == "APROBADA" and out["reviewer"]["username"] == "admin"


def test_linked_admin_can_decide_other_engineers(f, db):
    eng, card, area = f.setup()
    other, other_card, _ = f.setup()
    req = f.ok("POST", REQ, 201, json=_form(other, other_card, area, duration_minutes=60))
    _admin_linked_to(db, eng["id"])
    with _login_client("laura.admin") as c:
        r = c.post(f"{REQ}/{req['id']}/approve", json={})
        assert r.status_code == 200 and r.json()["reviewer"]["username"] == "laura.admin"


def test_engineer_links_to_a_single_admin(f, db):
    eng = f.engineer()
    _admin_linked_to(db, eng["id"])
    from app.core.errors import DomainError
    import pytest

    with pytest.raises(DomainError) as exc:
        create_admin(db, "otro.admin", ADMIN_PASSWORD, "Otro", AdminRole.ADMIN, engineer_id=eng["id"])
    assert exc.value.code == "ENGINEER_ALREADY_LINKED"
    db.rollback()
    assert db.execute(select(Admin).where(Admin.engineer_id == eng["id"])).scalar_one().username == "laura.admin"


def test_auditor_cannot_decide(f, auditor_api):
    eng, card, area = f.setup()
    req = f.ok("POST", REQ, 201, json=_form(eng, card, area, duration_minutes=60))
    assert auditor_api.post(f"{REQ}/{req['id']}/approve", json={}).status_code == 403
    assert auditor_api.post(REQ, json=_form(eng, card, area, duration_minutes=60)).status_code == 403
    assert auditor_api.get(f"{REQ}/{req['id']}").status_code == 200


# ----------------------------------------------------------------- listing
def test_stats_and_search(f):
    eng, card, area = f.setup()
    a = f.ok("POST", REQ, 201, json=_form(eng, card, area, utcnow() - timedelta(minutes=1), duration_minutes=60))
    b = f.ok("POST", REQ, 201, json=_form(eng, card, area, utcnow() + timedelta(hours=3), duration_minutes=60))
    f.ok("POST", REQ, 201, json=_form(eng, card, area, utcnow() + timedelta(hours=6), duration_minutes=60))
    f.ok("POST", f"{REQ}/{a['id']}/approve", json={})
    f.ok("POST", f"{REQ}/{b['id']}/reject", json={"notes": "Fuera de turno"})

    st = f.ok("GET", f"{REQ}/stats")
    assert st["by_status"]["PENDIENTE"] == 1 and st["by_status"]["APROBADA"] == 1
    assert st["by_status"]["RECHAZADA"] == 1 and st["in_force"] == 1 and st["total"] == 3

    other, other_card, _ = f.setup()
    f.ok("POST", REQ, 201, json=_form(other, other_card, area, duration_minutes=30))
    assert f.ok("GET", REQ, params={"q": eng["engineer_id"]})["total"] == 3
    assert f.ok("GET", REQ, params={"q": other_card["uid"]})["total"] == 1
    assert f.ok("GET", REQ, params={"q": "zzz-nada"})["total"] == 0
