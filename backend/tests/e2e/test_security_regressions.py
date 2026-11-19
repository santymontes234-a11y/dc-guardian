"""Regression tests for the F8 closing security review (one per fixed finding)."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.db.session import ReadSessionLocal
from app.models import AuditLog
from tests.e2e.conftest import esp32_sim

STRANGER = 999_002


def _inside(flow):
    """Engineer with an authorized card who has already entered (is inside)."""
    eng, card, req = flow.authorized()
    assert flow.access(card["uid"], face_seed=eng["_seed"]).outcome == "GRANTED_AND_CLOSED"
    flow.door.sim.set_distance(200)
    return eng, card, req


# ------------------------------------------------------------------ A1: exit needs the face
def test_exit_with_only_the_card_never_opens(flow):
    """Cloned / lent card used from outside on the single reader: no face, no door."""
    eng, card, _ = _inside(flow)
    out = flow.access(card["uid"], face_seed=STRANGER)
    assert out.outcome == "DENIED" and out.reason_code == "FACE_MISMATCH"
    d = flow.door.sim
    d.set_distance(30)
    sid = d.start(card["uid"]).data["session_id"]
    assert d.poll(sid).data["state"] == "AWAITING_FACE"  # waiting, never GRANTED on the card alone


def test_suspended_engineer_inside_can_still_leave_with_face(flow, f):
    eng, card, _ = _inside(flow)
    f.ok("POST", f"/api/v1/engineers/{eng['id']}/status", json={"status": "SUSPENDIDO", "reason": "Investigación"})
    # Card alone + stranger: denied (this used to open the door)
    assert flow.access(card["uid"], face_seed=STRANGER).outcome == "DENIED"
    # The engineer themself is never trapped: face OK → exit without authorization
    out = flow.access(card["uid"], face_seed=eng["_seed"])
    assert out.outcome == "GRANTED_AND_CLOSED", out.log
    assert f.ok("GET", f"/api/v1/access-sessions/{out.session_id}")["direction"] == "SALIDA"
    assert any(a["type"] == "INACTIVE_ENGINEER" and a["severity"] == "CRITICAL" for a in flow.alerts())


# ------------------------------------------------------------------ M1/M3: kiosk websocket
def test_kiosk_ws_token_in_first_message_and_no_card_uid(flow, f, device_client):
    from app.api.v1.kiosk import kiosk_token

    eng, card, _ = flow.authorized()
    with device_client.websocket_connect("/ws/events") as ws:
        ws.send_json({"kiosk_token": kiosk_token()})
        assert ws.receive_json()["data"]["role"] == "kiosk"
        flow.door.sim.set_distance(30)
        flow.door.sim.start(card["uid"])
        evt = ws.receive_json()
        while evt["type"] != "access.awaiting_face":
            evt = ws.receive_json()
    data = evt["data"]
    assert data["engineer"] == {"full_name": eng["full_name"]}
    for leaked in ("card_uid", "card_id", "request_id", "face_score", "presence_cm_start"):
        assert leaked not in data


def test_kiosk_token_in_url_is_not_accepted(device_client):
    from starlette.websockets import WebSocketDisconnect

    from app.api.v1.kiosk import kiosk_token

    with pytest.raises(WebSocketDisconnect) as e:
        with device_client.websocket_connect(f"/ws/events?kiosk_token={kiosk_token()}") as ws:
            ws.send_json({"hola": 1})
            ws.receive_json()
    assert e.value.code == 4401


# ------------------------------------------------------------------ M2/M3/B9: configuration
_STRONG = "x" * 48


def _settings(**over):
    from app.core.config import Settings

    base = dict(_env_file=None, env="prod", jwt_secret=_STRONG, master_key=_STRONG, cookie_secure=True,
                face_provider="insightface")
    return Settings(**{**base, **over})


def test_prod_rejects_the_mock_face_provider():
    with pytest.raises(ValueError, match="mock face provider"):
        _settings(face_provider="mock")
    assert _settings().face_provider == "insightface"


def test_short_kiosk_token_rejected():
    with pytest.raises(ValueError, match="KIOSK_TOKEN"):
        _settings(kiosk_token="1234")


# ------------------------------------------------------------------ M4/B5: gateway hardening
def test_gateway_rejects_oversized_body(flow, device_client):
    big = b'{"x":"' + b"a" * 5000 + b'"}'
    r = device_client.post("/api/v1/device/heartbeat", content=big, headers={"Content-Type": "application/json"})
    assert r.status_code == 413 and r.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_anonymous_flood_does_not_grow_the_audit_log(flow, device_client):
    with ReadSessionLocal() as db:
        before = db.execute(select(func.count()).select_from(AuditLog)).scalar_one()
    for _ in range(50):
        assert device_client.post("/api/v1/device/heartbeat", json={}).status_code == 401
    with ReadSessionLocal() as db:
        after = db.execute(select(func.count()).select_from(AuditLog)).scalar_one()
    assert after - before <= 12  # rate-limited: ~10 audit rows (+ one alert) instead of 50+


def test_duplicate_query_parameters_rejected(flow):
    d = flow.door.sim
    sid = "0" * 32
    import secrets as _s
    import time as _t

    path = f"/api/v1/device/access/{sid}"
    qs = "distance_cm=30.0&distance_cm=900.0"
    ts, nonce = str(int(_t.time())), _s.token_hex(16)
    sig = esp32_sim.sign(d.secret, esp32_sim.request_signing_string("GET", path, qs, ts, nonce, b""))
    status, _h, body = d.transport.request("GET", f"{path}?{qs}", {
        "X-Device-Id": d.device_id, "X-Timestamp": ts, "X-Nonce": nonce, "X-Signature": sig}, b"")
    assert status == 400 and b"DEVICE_BAD_QUERY" in body


# ------------------------------------------------------------------ B1: websocket after logout
def test_admin_websocket_closes_after_logout(flow, f, monkeypatch):
    from starlette.websockets import WebSocketDisconnect

    from app.ws import router as ws_router

    monkeypatch.setattr(ws_router, "REVALIDATE_S", 0.2)
    with f.c.websocket_connect("/ws/events") as ws:
        assert ws.receive_json()["type"] == "hello"
        f.ok("POST", "/api/v1/auth/logout", 204)
        with pytest.raises(WebSocketDisconnect) as e:
            for _ in range(20):
                ws.receive_json()
        assert e.value.code == 4401


# ------------------------------------------------------------------ B4: unknown cards
def test_unknown_card_does_not_cancel_someone_elses_attempt(flow):
    eng, card, _ = flow.authorized()
    d = flow.door.sim
    d.set_distance(30)
    sid = d.start(card["uid"]).data["session_id"]
    assert d.call("POST", "/device/access/start", body={"uid": "0BADC0DE", "distance_cm": 30}).data["reason_code"] \
        == "UNKNOWN_CARD"
    assert flow.kiosk(sid, eng["_seed"])["state"] == "FACE_OK"  # still alive
    assert d.poll(sid).data["state"] == "GRANTED"
