"""Main entrance: QR credential, kiosk scan, signed one-shot LED signal and the access log
(docs/contrato-qr-dht11.md §2, §3 y §6). The device side uses the real signed protocol."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.api.v1.kiosk import kiosk_token
from app.db.session import SessionLocal
from app.db.types import utcnow
from app.main import app as fastapi_app
from app.models import AuditLog, Device, EntranceEvent, QrCredential
from app.models.enums import DeviceStatus
from app.services.scheduler import run_access_sweep
from app.ws.hub import hub
from tests.e2e.conftest import esp32_sim

SCAN = "/api/v1/kiosk/entrance/scan"
QR_RE = re.compile(r"^DCG-QR1:[A-Za-z0-9_-]{32}$")
HEX32 = re.compile(r"^[0-9a-f]{32}$")


@pytest.fixture
def entrance(f):
    return f.area("ENTRADA_PRINCIPAL")


def issue(f, eng_id: int, **body) -> dict:
    return f.ok("POST", f"/api/v1/engineers/{eng_id}/qr", 201, json=body or None)


def scan(c, text: str, expected: int = 200) -> dict:
    r = c.post(SCAN, json={"qr_text": text})
    assert r.status_code == expected, r.text
    return r.json()


def poll(door) -> dict | None:
    r = door.sim.call("POST", "/device/entrance/poll", body={})  # raises BadResponse if not signed
    assert r.status == 200, r.data
    return r.data["signal"]


def ack(door, signal_id: str, shown: bool = True):
    return door.sim.call("POST", f"/device/entrance/{signal_id}/ack", body={"shown": shown})


def authorized_with_qr(flow, f) -> tuple[dict, dict, str]:
    eng, card, _req = flow.authorized()
    return eng, card, issue(f, eng["id"])["qr_text"]


# ------------------------------------------------------------------ admin API
def test_issue_status_and_revoke_qr(f, flow, auditor_api, db):
    eng = flow.engineer(face=False)
    out = issue(f, eng["id"])
    assert QR_RE.match(out["qr_text"])
    token = out["qr_text"].split(":", 1)[1]
    assert out["prefix"] == token[:6] and out["expires_at"] is None
    assert out["engineer"] == {"id": eng["id"], "full_name": eng["full_name"], "position": eng["position"]}

    st = f.ok("GET", f"/api/v1/engineers/{eng['id']}/qr")
    assert st["active"] is True and st["prefix"] == token[:6] and st["last_used_at"] is None
    assert "qr_text" not in st and token not in json.dumps(st)

    # Only the hash is stored, never the token (nor in the audit log).
    cred = db.execute(select(QrCredential)).scalar_one()
    assert cred.token_sha256 == hashlib.sha256(token.encode()).hexdigest()
    assert all(token not in (e.details_json or "") for e in db.execute(select(AuditLog)).scalars())

    # A new QR revokes the previous one.
    second = issue(f, eng["id"])["qr_text"]
    db.expire_all()
    assert scan(f.c, out["qr_text"])["reason_code"] == "QR_REVOKED"
    assert len(db.execute(select(QrCredential).where(QrCredential.status == "ACTIVA")).scalars().all()) == 1

    assert auditor_api.get(f"/api/v1/engineers/{eng['id']}/qr").status_code == 403
    assert auditor_api.post(f"/api/v1/engineers/{eng['id']}/qr").status_code == 403

    r = f.c.delete(f"/api/v1/engineers/{eng['id']}/qr")
    assert r.status_code == 204 and r.content == b""
    assert f.ok("GET", f"/api/v1/engineers/{eng['id']}/qr")["active"] is False
    assert scan(f.c, second)["reason_code"] == "QR_REVOKED"
    r = f.c.delete(f"/api/v1/engineers/{eng['id']}/qr")
    assert r.status_code == 404 and r.json()["error"]["code"] == "QR_NOT_FOUND"
    assert {"qr.issued", "qr.revoked"} <= set(flow.audit_actions(entity="qr_credential"))


def test_qr_rules_on_issue(f, flow):
    eng = flow.engineer(face=False)
    past = (utcnow() - timedelta(minutes=1)).isoformat()
    r = f.c.post(f"/api/v1/engineers/{eng['id']}/qr", json={"expires_at": past})
    assert r.status_code == 422 and r.json()["error"]["code"] == "QR_EXPIRES_IN_PAST"
    f.ok("POST", f"/api/v1/engineers/{eng['id']}/status", json={"status": "SUSPENDIDO", "reason": "Prueba"})
    r = f.c.post(f"/api/v1/engineers/{eng['id']}/qr")
    assert r.status_code == 409 and r.json()["error"]["code"] == "ENGINEER_NOT_ACTIVE"
    assert f.c.post("/api/v1/engineers/999999/qr").status_code == 404


def test_erasure_revokes_the_qr(f, flow):
    eng = flow.engineer(face=False)
    issue(f, eng["id"])
    f.ok("POST", f"/api/v1/engineers/{eng['id']}/erase",
         json={"confirm_engineer_id": eng["engineer_id"], "reason": "Derecho de supresión"})
    with SessionLocal() as db:
        assert db.execute(select(QrCredential.status)).scalar_one() == "REVOCADA"


# ------------------------------------------------------------------ scan: granted
def test_valid_qr_with_registro2_lights_the_entrance_led_once(f, flow, door, entrance):
    eng, _card, text = authorized_with_qr(flow, f)
    out = scan(f.c, text)
    assert out["result"] == "GRANTED" and out["area"] == "ENTRADA_PRINCIPAL"
    assert out["display_name"] == eng["full_name"] and out["position"] == eng["position"]
    assert HEX32.match(out["event_id"]) and "reason_code" not in out

    sig = poll(door)
    assert sig == {"id": out["event_id"], "result": "GRANTED", "led_ms": 5000,
                   "display_name": esp32_sim_ascii(eng["full_name"])}
    assert poll(door) is None  # delivered exactly once
    assert ack(door, sig["id"]).data == {"ok": True}
    assert ack(door, sig["id"]).data == {"ok": True}  # idempotent retry

    with SessionLocal() as db:
        ev = db.get(EntranceEvent, out["event_id"])
        assert ev.signal_status == "MOSTRADA" and ev.method == "QR" and ev.area_id == entrance["id"]
    assert door.sim.door == "CLOSED"  # the server-room servo is independent
    assert f.ok("GET", "/api/v1/access-sessions")["total"] == 0
    assert f.ok("GET", f"/api/v1/engineers/{eng['id']}/qr")["last_used_at"] is not None
    actions = flow.audit_actions(entity="entrance_event")
    assert actions == ["entrance.qr_granted", "entrance.signal_delivered", "entrance.signal_shown"]
    assert any(e["type"] == "entrance.scan" and e["data"]["result"] == "GRANTED" for e in hub.history)


def esp32_sim_ascii(name: str) -> str:
    from app.services.access_engine import ascii_text

    return ascii_text(name, 40)


def test_kiosk_token_scan_and_auth(f, flow, door, entrance, auditor_api):
    _eng, _card, text = authorized_with_qr(flow, f)
    with TestClient(fastapi_app) as anon:
        r = anon.post(SCAN, json={"qr_text": text})
        assert r.status_code == 401
        r = anon.post(SCAN, json={"qr_text": text}, headers={"X-Kiosk-Token": "x" * 40})
        assert r.status_code == 401 and r.json()["error"]["code"] == "KIOSK_TOKEN_INVALID"
        r = anon.post(SCAN, json={"qr_text": text}, headers={"X-Kiosk-Token": kiosk_token()})
        assert r.status_code == 200 and r.json()["result"] == "GRANTED"
    assert auditor_api.post(SCAN, json={"qr_text": text}).status_code == 403


# ------------------------------------------------------------------ scan: denials (contract order)
def _set_device(status: DeviceStatus | None = None, last_seen_delta_s: int | None = None):
    with SessionLocal() as db:
        values = {}
        if status is not None:
            values["status"] = status
        if last_seen_delta_s is not None:
            values["last_seen_at"] = utcnow() - timedelta(seconds=last_seen_delta_s)
        db.execute(update(Device).values(**values))
        db.commit()


def test_denials_follow_the_contract_order(f, flow, door, entrance):
    c = f.c
    assert scan(c, "hola mundo")["reason_code"] == "QR_INVALID"
    assert scan(c, "DCG-QR1:" + "A" * 31)["reason_code"] == "QR_INVALID"
    assert scan(c, "DCG-QR1:" + secrets.token_urlsafe(24))["reason_code"] == "QR_UNKNOWN"

    # Registro 1 alone (engineer + face + card + QR) never grants: no authorization.
    eng = flow.engineer()
    card = flow.card(eng)
    text = issue(f, eng["id"])["qr_text"]
    out = scan(c, text)
    assert out == {"result": "DENIED", "reason_code": "NO_VALID_AUTH", "reason": out["reason"],
                   "area": "ENTRADA_PRINCIPAL", "event_id": out["event_id"]}  # no identity on denial

    # Same reason codes as the RFID door for Registro 2.
    pending = flow.request(eng, card, start_delta_min=-1, approve=False)
    assert scan(c, text)["reason_code"] == "REQUEST_PENDING"
    f.ok("POST", f"/api/v1/requests/{pending['id']}/reject", json={"notes": "No procede"})
    assert scan(c, text)["reason_code"] == "AUTH_REJECTED"
    eng_f = flow.engineer(face=False)
    flow.request(eng_f, flow.card(eng_f), start_delta_min=30)
    assert scan(c, issue(f, eng_f["id"])["qr_text"])["reason_code"] == "AUTH_NOT_STARTED"

    # Expired QR (checked before the engineer and Registro 2).
    with SessionLocal() as db:
        db.execute(update(QrCredential).values(expires_at=utcnow() - timedelta(seconds=1)))
        db.commit()
    assert scan(c, text)["reason_code"] == "QR_EXPIRED"

    # Inactive engineer (checked before Registro 2).
    eng2, _card2, text2 = authorized_with_qr(flow, f)
    f.ok("POST", f"/api/v1/engineers/{eng2['id']}/status", json={"status": "INACTIVO", "reason": "Baja"})
    assert scan(c, text2)["reason_code"] == "ENGINEER_INACTIVE"

    # Everything valid but the entrance device is not ONLINE (or silent) → DEVICE_OFFLINE.
    _eng3, _card3, text3 = authorized_with_qr(flow, f)
    _set_device(status=DeviceStatus.OFFLINE)
    assert scan(c, text3)["reason_code"] == "DEVICE_OFFLINE"
    _set_device(status=DeviceStatus.ONLINE, last_seen_delta_s=600)
    assert scan(c, text3)["reason_code"] == "DEVICE_OFFLINE"
    _set_device(status=DeviceStatus.ONLINE, last_seen_delta_s=0)
    assert scan(c, text3)["result"] == "GRANTED"

    alert_types = {a["type"] for a in flow.alerts()}
    assert {"UNKNOWN_QR", "QR_BLOCKED", "NO_VALID_AUTH", "INACTIVE_ENGINEER"} <= alert_types
    assert "entrance.qr_denied" in flow.audit_actions(entity="entrance_event")


def test_denied_signal_has_no_name(f, flow, door, entrance):
    scan(f.c, "DCG-QR1:" + secrets.token_urlsafe(24))
    sig = poll(door)
    assert sig["result"] == "DENIED" and sig["display_name"] == "" and sig["led_ms"] == 5000


def test_scan_rate_limit(f, door, entrance):
    for _ in range(20):
        scan(f.c, "nope")
    r = f.c.post(SCAN, json={"qr_text": "nope"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "RATE_LIMITED"
    with SessionLocal() as db:  # the rejected scan is not logged
        assert db.query(EntranceEvent).count() == 20


# ------------------------------------------------------------------ signals
def _age_events(seconds: int) -> None:
    with SessionLocal() as db:
        db.execute(update(EntranceEvent).values(created_at=utcnow() - timedelta(seconds=seconds)))
        db.commit()


def test_signal_expires_after_10_s(f, flow, door, entrance):
    _eng, _card, text = authorized_with_qr(flow, f)
    out = scan(f.c, text)
    _age_events(11)
    assert poll(door) is None
    with SessionLocal() as db:
        assert db.get(EntranceEvent, out["event_id"]).signal_status == "EXPIRADA"
    r = ack(door, out["event_id"])
    assert r.status == 409 and r.data["error"]["code"] == "SIGNAL_NOT_DELIVERED"
    assert "entrance.signal_expired" in flow.audit_actions(entity="entrance_event")


def test_sweep_expires_undelivered_signals(f, door, entrance):
    scan(f.c, "nope")
    _age_events(30)
    assert run_access_sweep()["entrance_signals_expired"] == 1
    assert poll(door) is None


def test_signals_are_delivered_in_order_only_to_the_entrance_device(f, flow, door, entrance):
    other = f.ok("POST", "/api/v1/devices", 201, json={
        "device_code": "DC-DOOR-02", "name": "Otra", "area_id": door.area["id"]})
    sim2 = esp32_sim.Esp32Sim("DC-DOOR-02", other["secret"], door.sim.transport)
    a = scan(f.c, "nope")["event_id"]
    b = scan(f.c, "DCG-QR1:" + secrets.token_urlsafe(24))["event_id"]
    assert sim2.call("POST", "/device/entrance/poll", body={}).data == {"signal": None}
    r = sim2.call("POST", f"/device/entrance/{a}/ack", body={"shown": True})
    assert r.status == 404 and r.data["error"]["code"] == "SIGNAL_NOT_FOUND"
    assert [poll(door)["id"], poll(door)["id"], poll(door)] == [a, b, None]


def test_signal_responses_are_signed_and_bound_to_the_nonce(f, door, entrance):
    scan(f.c, "nope")
    transport = door.sim.transport
    # Unsigned request → 401 and nothing delivered.
    status, _headers, _body = transport.request("POST", "/api/v1/device/entrance/poll",
                                           {"Content-Type": "application/json"}, b"{}")
    assert status == 401
    # A tampered/invalid response signature is rejected by the device (fail-closed: LED off).
    door.sim.tamper_response = True
    with pytest.raises(esp32_sim.BadResponse):
        door.sim.call("POST", "/device/entrance/poll", body={})
    door.sim.tamper_response = False
    # Errors are signed too.
    r = ack(door, "0" * 32)
    assert r.status == 404 and r.data["error"]["code"] == "SIGNAL_NOT_FOUND"


def test_ack_shown_false_keeps_it_delivered(f, door, entrance):
    eid = scan(f.c, "nope")["event_id"]
    poll(door)
    assert ack(door, eid, shown=False).data == {"ok": True}
    with SessionLocal() as db:
        ev = db.get(EntranceEvent, eid)
        assert ev.signal_status == "ENTREGADA" and ev.acked_at is not None


def test_heartbeat_sends_dht_thresholds_and_accepts_dht_sensor(f, door):
    hb = door.sim.call("POST", "/device/heartbeat", body={"sensors": {"rfid": "OK", "ultrasonic": "OK",
                                                                      "dht": "ERROR"}})
    cfg = hb.data["config"]
    assert (cfg["temp_high_c"], cfg["temp_critical_c"], cfg["humidity_low_pct"], cfg["humidity_high_pct"]) == \
        (27, 32, 20, 80)
    hw = f.ok("GET", "/api/v1/devices/status/all")[0]["hw"]
    assert hw["sensors"]["dht"] == "ERROR"
    # The DHT has its own alert (SENSOR_DHT_ERROR via /device/environment), not SENSOR_FAULT.
    assert not [a for a in f.ok("GET", "/api/v1/alerts")["items"] if a["type"] == "SENSOR_FAULT"]


# ------------------------------------------------------------------ access log (bitácora)
ROW_KEYS = {"id", "source", "at", "person", "engineer_id", "position", "zone", "method", "direction",
            "result", "reason_code", "reason", "device_code"}


def test_access_log_lists_qr_and_rfid_with_zone_method_person(f, flow, door, entrance, auditor_api):
    eng, card, text = authorized_with_qr(flow, f)
    assert flow.access(card["uid"], face_seed=eng["_seed"]).outcome == "GRANTED_AND_CLOSED"
    scan(f.c, text)
    scan(f.c, "basura")

    log = auditor_api.get("/api/v1/access-log").json()
    assert log["total"] == 3
    rows = log["items"]
    assert all(set(r) == ROW_KEYS for r in rows)
    bad, qr_ok, rfid = rows  # newest first
    assert bad["method"] == "QR" and bad["result"] == "DENIED" and bad["reason_code"] == "QR_INVALID"
    assert bad["person"] is None and bad["zone"] == {"code": "ENTRADA_PRINCIPAL", "name": entrance["name"]}
    assert qr_ok == {**qr_ok, "method": "QR", "result": "GRANTED", "person": eng["full_name"],
                     "position": eng["position"], "engineer_id": eng["engineer_id"], "direction": "ENTRADA",
                     "reason_code": None, "device_code": "DC-DOOR-01"}
    assert rfid["method"] == "RFID+ROSTRO" and rfid["result"] == "GRANTED" and rfid["direction"] == "ENTRADA"
    assert rfid["zone"] == {"code": door.area["code"], "name": door.area["name"]}

    def q(**params):
        return f.ok("GET", "/api/v1/access-log", params=params)

    assert q(method="QR")["total"] == 2
    assert q(method="RFID+ROSTRO")["total"] == 1
    assert q(result="DENIED")["total"] == 1
    assert q(zone="ENTRADA_PRINCIPAL")["total"] == 2
    assert q(zone="NO_EXISTE")["total"] == 0
    assert q(engineer_id=eng["id"])["total"] == 2
    assert q(limit=1, offset=1)["items"][0]["id"] == qr_ok["id"]
    assert q(since=(utcnow() + timedelta(minutes=1)).isoformat())["total"] == 0
    assert f.c.get("/api/v1/access-log", params={"method": "FAX"}).status_code == 422
