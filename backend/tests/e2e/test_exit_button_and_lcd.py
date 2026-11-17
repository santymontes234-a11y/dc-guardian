"""Inside exit button (opens only if someone is inside) and the LCD greeting on GRANTED."""

from __future__ import annotations


def _enter(flow):
    eng, card, req = flow.authorized()
    res = flow.access(card["uid"], face_seed=eng["_seed"])
    assert res.outcome == "GRANTED_AND_CLOSED", res.log
    return eng, card, res


def _button_cycle(d):
    """Press the inside button and run poll → open → close like the firmware."""
    r = d.exit_button()
    if not d.session_id:
        return r, None
    sid = d.session_id
    p = d.poll(sid)
    open_ms = d.decide(p, sid)
    if open_ms is not None:
        d.opened(sid, open_ms)
        d.closed(sid, "TIMER")
    return r, p


def test_button_does_nothing_when_nobody_is_inside(flow, f):
    d = flow.door.sim
    r, _ = _button_cycle(d)
    assert (r.data["state"], r.data["reason_code"]) == ("DENIED", "NOBODY_INSIDE")
    assert d.door == "CLOSED"
    denied = f.ok("GET", "/api/v1/access-sessions", params={"reason_code": "NOBODY_INSIDE"})["items"]
    assert denied and denied[0]["direction"] == "SALIDA"


def test_button_opens_from_inside_without_presence_and_records_exit(flow, f):
    eng, card, _ = _enter(flow)
    d = flow.door.sim
    d.set_distance(200)  # nobody in front of the outside sensor
    d.sensors["ultrasonic"] = "TIMEOUT"  # even with the sensor failing, the inside button works
    r, p = _button_cycle(d)
    assert r.data["state"] == "FACE_OK"
    assert p.data["state"] == "GRANTED" and d.lcd == ("Hasta pronto", eng["full_name"])
    sess = f.ok("GET", f"/api/v1/access-sessions/{p.data['session_id']}")
    assert sess["direction"] == "SALIDA" and sess["state"] == "CLOSED"
    assert sess["engineer"]["engineer_id"] == eng["engineer_id"]
    assert "access.exit" in flow.audit_actions(entity="engineer", entity_id=str(eng["id"]))
    assert f.ok("GET", "/api/v1/stats/dashboard")["engineers"]["inside"] == []
    # Now nobody is inside: a second press does nothing.
    d.sensors["ultrasonic"] = "OK"
    r2, _ = _button_cycle(d)
    assert r2.data["reason_code"] == "NOBODY_INSIDE"


def test_button_with_several_people_inside_opens_without_attribution(flow, f):
    _enter(flow)
    _enter(flow)
    r, p = _button_cycle(flow.door.sim)
    assert p.data["state"] == "GRANTED" and p.data["display_name"] == ""
    assert any(a["type"] == "DEVICE_EVENT" and "2 personas" in a["message"] for a in flow.alerts())


def test_granted_reply_carries_ascii_welcome_for_the_lcd(flow, f):
    eng = flow.engineer()
    f.ok("PATCH", f"/api/v1/engineers/{eng['id']}", json={"full_name": "José Ñúñez Peña"})
    card = flow.card(eng)
    flow.request(eng, card)
    res = flow.access(card["uid"], face_seed=eng["_seed"])
    assert res.outcome == "GRANTED_AND_CLOSED", res.log
    assert flow.door.sim.lcd == ("Bienvenido", "Jose Nunez Pena")  # HD44780 has no accents
