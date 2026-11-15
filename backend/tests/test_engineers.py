import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models import AuditLog, AuthorizationRequest

BASE = "/api/v1/engineers"


def _body(**over):
    return {"full_name": "Ana Gil", "department": "TI", "position": "Ing",
            "institutional_email": "ana@dcguardian.edu", **over}


def test_create_engineer_grants_no_access(f, db):
    eng = f.engineer(institutional_email="LAURA@dcguardian.edu")
    assert eng["engineer_id"] == "ENG-0001"
    assert eng["institutional_email"] == "laura@dcguardian.edu"
    assert eng["status"] == "ACTIVO"
    assert eng["has_face"] is False and eng["face_embedding_reference"] is None and eng["cards"] == []
    assert eng["registration_date"]
    assert db.query(AuthorizationRequest).count() == 0
    entry = db.execute(select(AuditLog).where(AuditLog.action == "engineer.created")).scalar_one()
    assert "laura" not in entry.details_json  # no personal data in the immutable log


def test_ids_are_sequential_and_never_reused(f):
    assert f.ok("GET", f"{BASE}/next-id")["engineer_id"] == "ENG-0001"
    a, b = f.engineer(), f.engineer()
    assert (a["engineer_id"], b["engineer_id"]) == ("ENG-0001", "ENG-0002")
    f.ok("POST", f"{BASE}/{b['id']}/erase", json={"confirm_engineer_id": "ENG-0002", "reason": "Baja"})
    assert f.engineer()["engineer_id"] == "ENG-0003"
    assert f.ok("GET", f"{BASE}/next-id")["engineer_id"] == "ENG-0004"


def test_engineer_id_cannot_be_supplied(f):
    r = f.c.post(BASE, json=_body(engineer_id="ENG-0042"))
    assert r.status_code == 422


def test_initial_status_can_be_chosen_but_not_erased(f):
    assert f.engineer(status="INACTIVO")["status"] == "INACTIVO"
    r = f.c.post(BASE, json=_body(status="ELIMINADO"))
    assert r.status_code == 422


@pytest.mark.parametrize("field,value", [
    ("institutional_email", "no-es-correo"), ("full_name", "  "), ("department", ""), ("status", "OTRO"),
])
def test_create_validation(f, field, value):
    r = f.c.post(BASE, json=_body(**{field: value}))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_duplicate_email_rejected(f):
    f.engineer(institutional_email="a@dcguardian.edu")
    r = f.c.post(BASE, json=_body(institutional_email="A@DCGUARDIAN.EDU"))
    assert r.status_code == 409 and r.json()["error"]["code"] == "EMAIL_TAKEN"


def test_unique_engineer_id_enforced_by_db(db):
    from sqlalchemy.exc import IntegrityError

    from app.models import Engineer

    db.add_all([Engineer(engineer_id="ENG-0001", full_name="A", department="x", position="y",
                         institutional_email="a@x.edu"),
                Engineer(engineer_id="ENG-0001", full_name="B", department="x", position="y",
                         institutional_email="b@x.edu")])
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_institutional_domain_enforced(f, monkeypatch):
    monkeypatch.setattr(get_settings(), "institutional_email_domain", "dcguardian.edu")
    r = f.c.post(BASE, json=_body(institutional_email="ana@gmail.com"))
    assert r.status_code == 422 and r.json()["error"]["code"] == "EMAIL_NOT_INSTITUTIONAL"


def test_list_search_and_pagination(f):
    for name in ("Laura Méndez", "Carlos Ortega", "Laura Ríos"):
        f.engineer(full_name=name)
    page = f.ok("GET", BASE, params={"q": "laura"})
    assert page["total"] == 2
    page = f.ok("GET", BASE, params={"limit": 1, "offset": 1})
    assert page["total"] == 3 and len(page["items"]) == 1
    assert f.ok("GET", BASE, params={"q": "ENG-0002"})["total"] == 1
    # LIKE wildcards are escaped
    assert f.ok("GET", BASE, params={"q": "%"})["total"] == 0
    assert f.ok("GET", BASE, params={"has_face": "true"})["total"] == 0


def test_get_by_code(f):
    eng = f.engineer()
    assert f.ok("GET", f"{BASE}/by-code/eng-0001")["id"] == eng["id"]


def test_update_engineer_audits_field_names_only(f, db):
    eng = f.engineer()
    out = f.ok("PATCH", f"{BASE}/{eng['id']}", json={"position": "Jefa de turno"})
    assert out["position"] == "Jefa de turno"
    entry = db.execute(select(AuditLog).where(AuditLog.action == "engineer.updated")).scalar_one()
    assert "position" in entry.details_json and "Jefa de turno" not in entry.details_json
    # engineer_id is immutable
    r = f.c.patch(f"{BASE}/{eng['id']}", json={"engineer_id": "ENG-9999"})
    assert r.status_code == 422
    assert f.ok("GET", f"{BASE}/{eng['id']}")["engineer_id"] == eng["engineer_id"]


def test_update_email_uniqueness(f):
    a = f.engineer()
    b = f.engineer()
    r = f.c.patch(f"{BASE}/{b['id']}", json={"institutional_email": a["institutional_email"]})
    assert r.status_code == 409


def test_not_found(api):
    r = api.get(f"{BASE}/999")
    assert r.status_code == 404 and r.json()["error"]["code"] == "ENGINEER_NOT_FOUND"


def test_suspension_closes_open_requests(f):
    eng, card, area = f.setup()
    pending = f.request(eng, card, area)
    approved_src = f.request(eng, card, f.area())
    f.ok("POST", f"/api/v1/requests/{approved_src['id']}/approve", json={})

    res = f.ok("POST", f"{BASE}/{eng['id']}/status", json={"status": "SUSPENDIDO", "reason": "Investigación"})
    assert res["engineer"]["status"] == "SUSPENDIDO"
    assert res["requests_revoked"] == 1 and res["requests_rejected"] == 1
    assert f.ok("GET", f"/api/v1/requests/{pending['id']}")["status"] == "RECHAZADA"
    revoked = f.ok("GET", f"/api/v1/requests/{approved_src['id']}")
    assert revoked["status"] == "REVOCADA"
    assert revoked["reviewer"]["username"] == "admin"  # approver preserved
    assert "Investigación" in revoked["close_notes"]

    # Reactivation does not resurrect anything
    res = f.ok("POST", f"{BASE}/{eng['id']}/status", json={"status": "ACTIVO", "reason": "Caso cerrado"})
    assert res["requests_revoked"] == res["requests_rejected"] == 0
    assert f.ok("GET", f"/api/v1/requests/{approved_src['id']}")["status"] == "REVOCADA"


def test_status_unchanged_conflict_and_erased_not_settable(f):
    eng = f.engineer()
    r = f.c.post(f"{BASE}/{eng['id']}/status", json={"status": "ACTIVO", "reason": "nada"})
    assert r.status_code == 409
    r = f.c.post(f"{BASE}/{eng['id']}/status", json={"status": "ELIMINADO", "reason": "nada"})
    assert r.status_code == 422


def test_erasure_removes_personal_data(f, db):
    eng, card, area = f.setup()
    req = f.request(eng, card, area)
    r = f.c.post(f"{BASE}/{eng['id']}/erase", json={"confirm_engineer_id": "ENG-9999", "reason": "Solicitud"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "CONFIRMATION_MISMATCH"

    res = f.ok("POST", f"{BASE}/{eng['id']}/erase",
               json={"confirm_engineer_id": eng["engineer_id"], "reason": "Derecho de supresión"})
    out = res["engineer"]
    assert out["status"] == "ELIMINADO" and out["engineer_id"] == eng["engineer_id"]
    assert eng["full_name"] not in out["full_name"] and out["institutional_email"].endswith("@invalid")
    assert out["cards"] == [] and res["cards_unlinked"] == 1 and res["requests_rejected"] == 1
    assert f.ok("GET", f"/api/v1/requests/{req['id']}")["status"] == "RECHAZADA"
    # Hidden from the default list, terminal for every write
    assert f.ok("GET", BASE)["total"] == 0
    assert f.ok("GET", BASE, params={"status": "ELIMINADO"})["total"] == 1
    assert f.c.patch(f"{BASE}/{eng['id']}", json={"position": "Otro cargo"}).status_code == 409
    assert f.c.post(f"{BASE}/{eng['id']}/status", json={"status": "ACTIVO", "reason": "volver"}).status_code == 409
    # The email is free again
    assert f.engineer(institutional_email=eng["institutional_email"])["status"] == "ACTIVO"
    entry = db.execute(select(AuditLog).where(AuditLog.action == "engineer.erased")).scalar_one()
    assert eng["institutional_email"] not in entry.details_json


def test_auditor_reads_but_cannot_write(f, auditor_api):
    eng = f.engineer()
    assert auditor_api.get(f"{BASE}/{eng['id']}").status_code == 200
    assert auditor_api.post(BASE, json=_body()).status_code == 403
    assert auditor_api.patch(f"{BASE}/{eng['id']}", json={"position": "Hack"}).status_code == 403
    r = auditor_api.post(f"{BASE}/{eng['id']}/erase", json={"confirm_engineer_id": eng["engineer_id"], "reason": "x y z"})
    assert r.status_code == 403


def test_anonymous_rejected(client):
    assert client.get(BASE).status_code == 401
