"""End-to-end verification of every flow requested for F8 (see docs/pruebas-integracion.md).

Each test drives the real stack: virtual ESP32 with the signed protocol → /device gateway →
access engine → kiosk 1:1 verification (MockFaceProvider) → audit / alerts / WS / dashboard.
"""

from __future__ import annotations

from datetime import timedelta

from app.db.types import utcnow
from app.services.scheduler import run_access_sweep
from app.ws.hub import hub
from tests.e2e.conftest import esp32_sim

STRANGER = 999_001


def _events(prefix: str) -> list[dict]:
    return [e for e in hub.history if e["type"].startswith(prefix)]


# ================================================================== happy path (18 steps)
def test_full_flow_entry_door_close_and_exit(flow, f):
    # 1–4: engineer registered, face captured, ID generated, card linked
    eng = flow.engineer()
    card = flow.card(eng)
    assert eng["engineer_id"].startswith("ENG-")
    detail = f.ok("GET", f"/api/v1/engineers/{eng['id']}")
    assert detail["has_face"] is True
    # Registro 1 alone grants nothing: no request yet → denied
    res = flow.access(card["uid"], face_seed=eng["_seed"])
    assert (res.outcome, res.reason_code) == ("DENIED", "NO_VALID_AUTH")

    # 5–6: request + approval (Registro 2)
    req = flow.request(eng, card)
    # 7–17: presence → card → backend → kiosk face → in force → servo opens → closes
    res = flow.access(card["uid"], face_seed=eng["_seed"])
    assert res.outcome == "GRANTED_AND_CLOSED", res.log
    assert res.open_ms == 5000
    assert res.kiosk["state"] == "FACE_OK" and res.kiosk["matches"] >= 3

    sess = f.ok("GET", f"/api/v1/access-sessions/{res.session_id}")
    assert sess["state"] == "CLOSED" and sess["direction"] == "ENTRADA"
    assert sess["engineer"]["engineer_id"] == eng["engineer_id"] and sess["request_id"] == req["id"]
    assert sess["face_score"] >= 0.45 and sess["opened_at"] and sess["closed_at"]
    assert f.ok("GET", f"/api/v1/requests/{req['id']}")["use_count"] == 1

    # 16–17 audited in order, with one correlation per request
    actions = flow.audit_actions(entity_id=res.session_id)
    assert actions == ["access.card_read", "access.awaiting_face", "access.face_ok", "access.granted",
                       "access.entry", "access.door_closed"]
    dash = f.ok("GET", "/api/v1/stats/dashboard")
    assert [e["engineer_id"] for e in dash["engineers"]["inside"]] == [eng["engineer_id"]]
    assert dash["access"]["entries_24h"] == 1

    # 18: second card pass = exit: face required (single reader), authorization not
    flow.door.sim.set_distance(200)
    out = flow.access(card["uid"], face_seed=eng["_seed"])
    assert out.outcome == "GRANTED_AND_CLOSED", out.log
    exit_sess = f.ok("GET", f"/api/v1/access-sessions/{out.session_id}")
    assert exit_sess["direction"] == "SALIDA" and exit_sess["state"] == "CLOSED"
    assert "access.exit" in flow.audit_actions(entity="engineer", entity_id=str(eng["id"]))
    dash = f.ok("GET", "/api/v1/stats/dashboard")
    assert dash["engineers"]["inside"] == [] and dash["access"]["exits_24h"] == 1
    assert f.ok("GET", "/api/v1/requests/{}".format(req["id"]))["use_count"] == 1  # exit does not consume

    # real-time events reached the hub for the dashboard
    kinds = [e["type"] for e in _events("access.")]
    for k in ("access.awaiting_face", "access.face_ok", "access.granted", "access.opened", "access.closed"):
        assert k in kinds
    assert "access.exit_requested" in flow.audit_actions(entity_id=out.session_id)
    assert f.ok("GET", "/api/v1/audit/verify")["ok"] is True


def test_correct_access_is_fast_and_clean(flow, f):
    eng, card, _ = flow.authorized()
    res = flow.access(card["uid"], face_seed=eng["_seed"])
    assert res.outcome == "GRANTED_AND_CLOSED"
    assert [a for a in flow.alerts() if a["session_id"] == res.session_id] == []


# ================================================================== denials
def _assert_denied(flow, f, res, reason, alert_type=None, severity=None):
    assert res.outcome == "DENIED", res.log
    assert res.reason_code == reason
    assert flow.door.sim.door == "CLOSED"  # never opened
    denied = f.ok("GET", "/api/v1/access-sessions", params={"state": "DENIED", "reason_code": reason})["items"]
    assert denied and denied[0]["reason"]  # reason shown to the operator, in Spanish
    assert any(e["type"] == "access.denied" and e["data"]["reason_code"] == reason for e in hub.history)
    if alert_type:
        alerts = [a for a in flow.alerts() if a["type"] == alert_type]
        assert alerts, f"no {alert_type} alert"
        if severity:
            assert alerts[0]["severity"] == severity
    return denied[0]


def test_unknown_engineer(flow, f):
    # Card registered but not bound to any engineer: nobody to verify against.
    card = flow.card(None)
    res = flow.access(card["uid"], face_seed=STRANGER)
    _assert_denied(flow, f, res, "CARD_NOT_LINKED", "CARD_NOT_LINKED")
    # An unregistered person with a valid, authorized card: the 1:1 face check fails.
    eng, card, _ = flow.authorized()
    res = flow.access(card["uid"], face_seed=STRANGER)
    _assert_denied(flow, f, res, "FACE_MISMATCH", "FACE_MISMATCH")


def test_unknown_rfid(flow, f):
    res = flow.access("0BADC0DE", face_seed=None)
    _assert_denied(flow, f, res, "UNKNOWN_CARD", "UNKNOWN_CARD", "WARN")


def test_wrong_rfid(flow, f):
    eng, card, _ = flow.authorized()
    # The engineer's *other* card: valid card, but the authorization is bound to the first one.
    other = flow.card(eng)
    res = flow.access(other["uid"], face_seed=eng["_seed"])
    _assert_denied(flow, f, res, "NO_VALID_AUTH", "NO_VALID_AUTH")
    # A blocked card.
    f.ok("POST", f"/api/v1/cards/{card['id']}/status", json={"status": "BLOQUEADA", "reason": "Prueba de bloqueo"})
    res = flow.access(card["uid"], face_seed=eng["_seed"])
    _assert_denied(flow, f, res, "CARD_NOT_ACTIVE", "CARD_BLOCKED")


def test_wrong_face(flow, f):
    eng, card, _ = flow.authorized()
    other = flow.engineer()  # a registered colleague tries with the first engineer's card
    res = flow.access(card["uid"], face_seed=other["_seed"])
    assert res.kiosk["state"] == "DENIED" and res.kiosk["reason_code"] == "FACE_MISMATCH"
    _assert_denied(flow, f, res, "FACE_MISMATCH", "FACE_MISMATCH")


def test_identical_frames_fail_liveness(flow, f):
    eng, card, _ = flow.authorized()
    d = flow.door.sim
    d.set_distance(30)
    sid = d.start(card["uid"]).data["session_id"]
    from tests.faces import capture, person

    photo = capture(person(eng["_seed"]), 1)  # the same photo five times
    r = f.c.post("/api/v1/vision/verify", data={"session_id": sid},
                 files=[("frames", (f"f{i}.jpg", photo, "image/jpeg")) for i in range(5)])
    assert r.json()["reason_code"] == "LIVENESS_FAILED"
    assert d.poll(sid).data["state"] == "DENIED"


def test_suspended_engineer(flow, f):
    eng, card, req = flow.authorized()
    r = f.ok("POST", f"/api/v1/engineers/{eng['id']}/status", json={"status": "SUSPENDIDO", "reason": "Investigación"})
    assert r["requests_revoked"] == 1  # suspending revokes the approved request (fail-closed)
    res = flow.access(card["uid"], face_seed=eng["_seed"])
    _assert_denied(flow, f, res, "ENGINEER_INACTIVE", "INACTIVE_ENGINEER", "CRITICAL")


def test_expired_authorization(flow, f):
    eng, card, req = flow.authorized()
    flow.shift_window_to_past(req["id"])
    # Even before the sweeper runs (still APROBADA in the DB) the engine checks the window itself.
    res = flow.access(card["uid"], face_seed=eng["_seed"])
    _assert_denied(flow, f, res, "AUTH_EXPIRED", "NO_VALID_AUTH")
    from app.services.scheduler import run_once

    run_once()
    assert f.ok("GET", f"/api/v1/requests/{req['id']}")["status"] == "EXPIRADA"
    res = flow.access(card["uid"], face_seed=eng["_seed"])
    assert res.reason_code == "AUTH_EXPIRED"


def test_pending_request(flow, f):
    eng = flow.engineer()
    card = flow.card(eng)
    flow.request(eng, card, approve=False)
    res = flow.access(card["uid"], face_seed=eng["_seed"])
    _assert_denied(flow, f, res, "REQUEST_PENDING", "NO_VALID_AUTH", "INFO")


def test_revoked_authorization(flow, f):
    eng, card, req = flow.authorized()
    f.ok("POST", f"/api/v1/requests/{req['id']}/revoke", json={"notes": "Ya no es necesario"})
    res = flow.access(card["uid"], face_seed=eng["_seed"])
    _assert_denied(flow, f, res, "AUTH_REVOKED", "NO_VALID_AUTH")


def test_revoked_between_face_and_opening(flow, f):
    """Step 14: validity is re-checked at the moment of opening, not only at card read."""
    eng, card, req = flow.authorized()
    d = flow.door.sim
    d.set_distance(30)
    sid = d.start(card["uid"]).data["session_id"]
    assert flow.kiosk(sid, eng["_seed"])["state"] == "FACE_OK"
    f.ok("POST", f"/api/v1/requests/{req['id']}/revoke", json={"notes": "Revocada a mitad de intento"})
    p = d.poll(sid)
    assert (p.data["state"], p.data["reason_code"]) == ("DENIED", "AUTH_REVOKED")
    assert d.decide(p, sid) is None


def test_presence_lost_and_timeout(flow, f):
    eng, card, _ = flow.authorized()
    d = flow.door.sim
    d.set_distance(30)
    sid = d.start(card["uid"]).data["session_id"]
    flow.kiosk(sid, eng["_seed"])
    d.set_distance(120)  # walks away before the decision
    p = d.poll(sid)
    assert (p.data["state"], p.data["reason_code"]) == ("DENIED", "PRESENCE_LOST")
    # Timeout: nobody looks at the camera within DCG_ACCESS_SESSION_TIMEOUT_S
    d.set_distance(30)
    sid = d.start(card["uid"]).data["session_id"]
    counts = run_access_sweep(utcnow() + timedelta(seconds=31))
    assert counts["timeouts"] == 1
    assert d.poll(sid).data["state"] == "TIMEOUT"


def test_repeated_failures_lock_the_card(flow, f):
    eng, card, _ = flow.authorized()
    for _ in range(3):
        flow.access(card["uid"], face_seed=STRANGER)
    assert any(a["type"] == "REPEATED_FAILURES" and a["severity"] == "CRITICAL" for a in flow.alerts())
    # Even the legitimate face is now refused until the lock expires or an admin unlocks it.
    res = flow.access(card["uid"], face_seed=eng["_seed"])
    assert res.reason_code == "CARD_LOCKED"


# ================================================================== hardware
def test_esp32_disconnected(flow, f):
    dev = flow.door.device
    status = {d["device_code"]: d for d in f.ok("GET", "/api/v1/devices/status/all")}
    assert status["DC-DOOR-01"]["status"] == "ONLINE"
    # No heartbeat for longer than DCG_DEVICE_OFFLINE_S → OFFLINE + alert
    counts = run_access_sweep(utcnow() + timedelta(seconds=46))
    assert counts["offline"] == 1
    status = {d["device_code"]: d for d in f.ok("GET", "/api/v1/devices/status/all")}
    assert status["DC-DOOR-01"]["status"] == "OFFLINE"
    assert any(a["type"] == "DEVICE_OFFLINE" and a["device_id"] == dev["id"] for a in flow.alerts())
    assert any(e["type"] == "device.status" and e["data"]["status"] == "OFFLINE" for e in hub.history)
    # It comes back with the next signed heartbeat
    flow.door.sim.heartbeat()
    assert f.ok("GET", f"/api/v1/devices/{dev['id']}")["status"] == "ONLINE"

    # From the device side, an unreachable backend means: no decision, door stays closed.
    class Down:
        def request(self, *a, **kw):
            raise OSError("connection refused")

    offline = esp32_sim.Esp32Sim("DC-DOOR-01", flow.door.secret, Down())
    try:
        offline.heartbeat()
        raise AssertionError("expected a network error")
    except OSError:
        assert offline.door == "CLOSED"


def test_sensor_without_response(flow, f):
    eng, card, _ = flow.authorized()
    d = flow.door.sim
    # Heartbeat reports the HC-SR04 timing out → SENSOR_FAULT alert + hardware status
    d.sensors = {"rfid": "OK", "ultrasonic": "TIMEOUT"}
    d.heartbeat()
    hw = {x["device_code"]: x for x in f.ok("GET", "/api/v1/devices/status/all")}["DC-DOOR-01"]["hw"]
    assert hw["sensors"]["ultrasonic"] == "TIMEOUT" and hw["distance_cm"] == -1
    assert any(a["type"] == "SENSOR_FAULT" for a in flow.alerts())
    # A card read with no valid distance is refused (fail-closed), even with a valid card.
    r = d.call("POST", "/device/access/start", body={"uid": card["uid"], "distance_cm": -1})
    assert (r.data["state"], r.data["reason_code"]) == ("DENIED", "SENSOR_ERROR")
    # Sensor dies at decision time (after a good face match) → denied
    d.sensors = {"rfid": "OK", "ultrasonic": "OK"}
    d.set_distance(30)
    sid = d.start(card["uid"]).data["session_id"]
    flow.kiosk(sid, eng["_seed"])
    d.sensors["ultrasonic"] = "TIMEOUT"
    p = d.poll(sid)
    assert (p.data["state"], p.data["reason_code"]) == ("DENIED", "SENSOR_ERROR")


# ================================================================== protocol security
def test_device_protocol_rejects_forgery_and_replay(flow, f, device_client):
    d = flow.door.sim
    # Bad signature → 401, signed reply, CRITICAL alert
    r = d.call("POST", "/device/heartbeat", body={}, signature="0" * 64)
    assert r.status == 401 and r.data["error"]["code"] == "DEVICE_AUTH_FAILED"
    assert any(a["type"] == "DEVICE_AUTH_FAIL" and a["severity"] == "CRITICAL" for a in flow.alerts())
    # Replay of a nonce
    d.call("POST", "/device/heartbeat", body={}, nonce="ab" * 16)
    r = d.call("POST", "/device/heartbeat", body={}, nonce="ab" * 16)
    assert r.data["error"]["code"] == "DEVICE_REPLAY"
    # Stale timestamp
    r = d.call("POST", "/device/heartbeat", body={}, ts=int(utcnow().timestamp()) - 120)
    assert r.data["error"]["code"] == "DEVICE_CLOCK_SKEW"
    # Unknown device → unsigned 401, which the ESP32 discards
    ghost = esp32_sim.Esp32Sim("DC-GHOST-99", "f" * 64, esp32_sim.ClientTransport(device_client))
    try:
        ghost.heartbeat()
        raise AssertionError("unsigned response must be rejected")
    except esp32_sim.BadResponse:
        pass
    # A tampered GRANTED never opens the door
    eng, card, _ = flow.authorized()
    d.set_distance(30)
    sid = d.start(card["uid"]).data["session_id"]
    flow.kiosk(sid, eng["_seed"])
    d.tamper_response = True
    try:
        d.poll(sid)
        raise AssertionError("tampered response accepted")
    except esp32_sim.BadResponse:
        assert d.door == "CLOSED"


def test_response_signature_matches_firmware_vector():
    """Shared vector with firmware/esp32-door/test/test_signing (secret 0011…eeff ×2)."""
    from app.core.security import device_response_signing_string, hmac_sign

    secret = "00112233445566778899aabbccddeeff" * 2
    msg = device_response_signing_string("GET", "/api/v1/device/access/0123456789abcdef0123456789abcdef",
                                         "0123456789abcdef0123456789abcdef", 200, "1763130001", b"")
    assert esp32_sim.response_signing_string("GET", "/api/v1/device/access/0123456789abcdef0123456789abcdef",
                                             "0123456789abcdef0123456789abcdef", 200, "1763130001", b"") == msg
    assert len(hmac_sign(secret, msg)) == 64


def test_emergency_close_via_heartbeat(flow, f):
    dev = flow.door.device
    f.ok("POST", f"/api/v1/devices/{dev['id']}/emergency-close")
    assert flow.door.sim.heartbeat().data["command"] == "EMERGENCY_CLOSE"
    assert flow.door.sim.heartbeat().data["command"] is None  # one-shot


# ================================================================== dashboard + realtime
def test_dashboard_shows_everything(flow, f):
    eng, card, _ = flow.authorized()
    flow.access(card["uid"], face_seed=eng["_seed"])
    flow.access("0BADC0DE", face_seed=None)
    dash = f.ok("GET", "/api/v1/stats/dashboard")
    assert dash["engineers"]["total"] == 1
    assert dash["requests"]["by_status"]["APROBADA"] == 1 and dash["requests"]["in_force"] == 1
    assert dash["access"]["entries_24h"] == 1 and dash["access"]["denied_24h"] == 1
    assert dash["denials_by_reason"][0]["reason_code"] == "UNKNOWN_CARD"
    assert dash["alerts"]["open_total"] >= 1
    assert dash["devices"][0]["status"] == "ONLINE"
    assert len(dash["recent_sessions"]) == 2 and dash["recent_denials"][0]["reason_code"] == "UNKNOWN_CARD"
    # auditors can read the dashboard but not act
    alert_id = dash["alerts"]["latest"][0]["id"]
    assert f.ok("POST", f"/api/v1/alerts/{alert_id}/ack")["acknowledged_at"]


def test_websocket_streams_events(flow, f):
    with f.c.websocket_connect("/ws/events") as ws:
        assert ws.receive_json()["type"] == "hello"
        flow.access("0BADC0DE", face_seed=None)
        seen = set()
        for _ in range(10):
            seen.add(ws.receive_json()["type"])
            if {"access.denied", "alert.created"} <= seen:
                break
        assert {"access.denied", "alert.created"} <= seen


def test_websocket_requires_auth(client):
    from starlette.websockets import WebSocketDisconnect

    try:
        with client.websocket_connect("/ws/events") as ws:
            ws.send_json({"kiosk_token": "incorrecto"})
            ws.receive_json()
        raise AssertionError("anonymous websocket accepted")
    except WebSocketDisconnect as e:
        assert e.code == 4401
