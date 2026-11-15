from app.core.security import decrypt_secret
from app.models import Device

CARDS = "/api/v1/cards"


# ----------------------------------------------------------------- cards
def test_card_uid_normalized_and_unique(f):
    card = f.card(uid="04:a1:b2:c3")
    assert card["uid"] == "04A1B2C3" and card["engineer"] is None
    r = f.c.post(CARDS, json={"uid": "04A1B2C3"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "CARD_UID_TAKEN"
    assert f.c.post(CARDS, json={"uid": "ZZ-not-hex"}).status_code == 422


def test_assign_and_unassign(f):
    eng = f.engineer()
    card = f.card()
    out = f.ok("POST", f"{CARDS}/{card['id']}/assign", json={"engineer_id": eng["id"]})
    assert out["engineer"]["id"] == eng["id"] and out["assigned_at"]
    assert f.ok("GET", f"/api/v1/engineers/{eng['id']}")["cards"][0]["uid"] == card["uid"]
    out = f.ok("POST", f"{CARDS}/{card['id']}/assign", json={"engineer_id": None})
    assert out["engineer"] is None and out["assigned_at"] is None


def test_cannot_assign_to_inactive_engineer(f):
    eng = f.engineer()
    f.ok("POST", f"/api/v1/engineers/{eng['id']}/status", json={"status": "INACTIVO", "reason": "Baja"})
    card = f.card()
    r = f.c.post(f"{CARDS}/{card['id']}/assign", json={"engineer_id": eng["id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "ENGINEER_NOT_ACTIVE"


def test_cannot_reassign_card_with_open_requests(f):
    eng, card, area = f.setup()
    f.request(eng, card, area)
    other = f.engineer()
    r = f.c.post(f"{CARDS}/{card['id']}/assign", json={"engineer_id": other["id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "CARD_HAS_OPEN_REQUESTS"


def test_lost_card_closes_requests_and_is_terminal(f):
    eng, card, area = f.setup()
    req = f.request(eng, card, area)
    f.ok("POST", f"/api/v1/requests/{req['id']}/approve", json={})
    res = f.ok("POST", f"{CARDS}/{card['id']}/status", json={"status": "PERDIDA", "reason": "Extraviada"})
    assert res["requests_revoked"] == 1
    assert f.ok("GET", f"/api/v1/requests/{req['id']}")["status"] == "REVOCADA"

    r = f.c.post(f"{CARDS}/{card['id']}/status", json={"status": "ACTIVA", "reason": "Apareció"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_TRANSITION"
    r = f.c.post(f"{CARDS}/{card['id']}/assign", json={"engineer_id": None})
    assert r.status_code == 409 and r.json()["error"]["code"] == "CARD_NOT_ASSIGNABLE"
    f.ok("POST", f"{CARDS}/{card['id']}/status", json={"status": "BAJA", "reason": "Destruida"})
    r = f.c.post(f"{CARDS}/{card['id']}/status", json={"status": "BLOQUEADA", "reason": "x" * 5})
    assert r.status_code == 409


def test_block_keeps_requests_and_unblock(f):
    eng, card, area = f.setup()
    req = f.request(eng, card, area)
    res = f.ok("POST", f"{CARDS}/{card['id']}/status", json={"status": "BLOQUEADA", "reason": "Revisión"})
    assert res["requests_revoked"] == res["requests_rejected"] == 0
    assert f.ok("GET", f"/api/v1/requests/{req['id']}")["status"] == "PENDIENTE"
    # cannot approve while the card is blocked
    r = f.c.post(f"/api/v1/requests/{req['id']}/approve", json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "CARD_NOT_ACTIVE"
    f.ok("POST", f"{CARDS}/{card['id']}/status", json={"status": "ACTIVA", "reason": "Revisada"})
    f.ok("POST", f"/api/v1/requests/{req['id']}/approve", json={})


def test_list_filters(f):
    eng = f.engineer()
    f.card(eng["id"])
    f.card()
    assert f.ok("GET", CARDS, params={"unassigned": True})["total"] == 1
    assert f.ok("GET", CARDS, params={"engineer_id": eng["id"]})["total"] == 1


# ----------------------------------------------------------------- areas
def test_area_crud_and_in_use(f):
    area = f.area("SALA-1")
    assert area["code"] == "SALA-1"
    assert f.c.post("/api/v1/areas", json={"code": "sala-1", "name": "Dup"}).status_code == 409
    f.ok("PATCH", f"/api/v1/areas/{area['id']}", json={"security_level": 5})
    assert f.c.patch(f"/api/v1/areas/{area['id']}", json={"security_level": 9}).status_code == 422

    eng = f.engineer()
    card = f.card(eng["id"])
    f.request(eng, card, area)
    r = f.c.delete(f"/api/v1/areas/{area['id']}")
    assert r.status_code == 409 and r.json()["error"]["code"] == "AREA_IN_USE"
    spare = f.area()
    assert f.c.delete(f"/api/v1/areas/{spare['id']}").status_code == 204


# ----------------------------------------------------------------- devices
def _device(f, **over):
    area = f.area()
    body = {"device_code": "DC-DOOR-09", "name": "Puerta de prueba", "area_id": area["id"], **over}
    return f.ok("POST", "/api/v1/devices", 201, json=body)


def test_device_secret_shown_once_and_stored_encrypted(f, db):
    created = _device(f)
    secret = created["secret"]
    assert len(secret) == 64
    dev_id = created["device"]["id"]
    assert "secret" not in f.c.get(f"/api/v1/devices/{dev_id}").text
    assert secret not in f.c.get("/api/v1/devices").text
    row = db.get(Device, dev_id)
    assert row.secret_encrypted != secret and decrypt_secret(row.secret_encrypted) == secret
    # nor in the audit log
    assert secret not in f.c.get("/api/v1/audit").text


def test_rotate_secret(f, db):
    created = _device(f)
    rotated = f.ok("POST", f"/api/v1/devices/{created['device']['id']}/rotate-secret")
    assert rotated["secret"] != created["secret"]
    db.expire_all()
    assert decrypt_secret(db.get(Device, created["device"]["id"]).secret_encrypted) == rotated["secret"]


def test_device_disable_enable_and_validation(f):
    created = _device(f)
    url = f"/api/v1/devices/{created['device']['id']}"
    assert f.ok("PATCH", url, json={"enabled": False})["status"] == "DESHABILITADO"
    assert f.ok("PATCH", url, json={"enabled": True})["status"] == "OFFLINE"
    assert f.c.patch(url, json={"presence_threshold_cm": 1}).status_code == 422
    assert f.c.patch(url, json={"area_id": 999}).status_code == 404


def test_auditor_cannot_create_device_or_rotate(f, auditor_api):
    created = _device(f)
    assert auditor_api.post(f"/api/v1/devices/{created['device']['id']}/rotate-secret").status_code == 403
    assert auditor_api.get("/api/v1/devices").status_code == 200
