"""Inside HC-SR04 = intrusion detector: alarm only when nobody authorized is inside."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import update

from app.db.session import SessionLocal
from app.db.types import utcnow
from app.models import AccessSession
from app.ws.hub import hub


def _age_door_cycles(seconds: int = 60) -> None:
    """Simulate that the last door cycle ended a while ago (outside the door grace)."""
    with SessionLocal() as db:
        past = utcnow() - timedelta(seconds=seconds)
        db.execute(update(AccessSession).where(AccessSession.closed_at.is_not(None)).values(closed_at=past))
        db.commit()


def test_someone_inside_with_nobody_authorized_triggers_the_alarm(flow, f):
    d = flow.door.sim
    d.set_distance(200)
    r = d.set_distance(10)
    assert r.data["alarm"] is True and r.data["alarm_s"] == 20
    assert d.alarm_s == 20
    alert = next(a for a in flow.alerts() if a["type"] == "INTRUSION")
    assert alert["severity"] == "CRITICAL" and "nadie autorizado" in alert["message"]
    assert "device.intrusion" in flow.audit_actions(action="device.")
    assert any(e["type"] == "alert.created" and e["data"]["type"] == "INTRUSION" for e in hub.history)
    assert d.door == "CLOSED"  # the alarm never opens anything


def test_no_alarm_while_an_authorized_engineer_is_inside(flow, f):
    eng, card, _ = flow.authorized()
    assert flow.access(card["uid"], face_seed=eng["_seed"]).outcome == "GRANTED_AND_CLOSED"
    _age_door_cycles()
    d = flow.door.sim
    d.set_distance(200)
    r = d.set_distance(10)
    assert r.data["alarm"] is False
    assert not [a for a in flow.alerts() if a["type"] == "INTRUSION"]


def test_alarm_again_after_the_engineer_left(flow, f):
    eng, card, _ = flow.authorized()
    assert flow.access(card["uid"], face_seed=eng["_seed"]).outcome == "GRANTED_AND_CLOSED"
    flow.door.sim.set_distance(200)
    assert flow.access(card["uid"], face_seed=eng["_seed"]).outcome == "GRANTED_AND_CLOSED"  # exit
    _age_door_cycles()
    d = flow.door.sim
    d.set_distance(200)
    assert d.set_distance(10).data["alarm"] is True


def test_crossing_the_door_is_not_an_intrusion(flow, f):
    """Right after a door cycle the person walking past the inside sensor is expected."""
    eng, card, _ = flow.authorized()
    assert flow.access(card["uid"], face_seed=eng["_seed"]).outcome == "GRANTED_AND_CLOSED"
    flow.door.sim.set_distance(200)
    assert flow.access(card["uid"], face_seed=eng["_seed"]).outcome == "GRANTED_AND_CLOSED"  # exit
    d = flow.door.sim
    d.set_distance(200)
    assert d.set_distance(10).data["alarm"] is False  # within the 15 s door grace


def test_leaving_the_room_never_alarms(flow, f):
    d = flow.door.sim
    d.set_distance(10)
    r = d.set_distance(200)
    assert r.data["alarm"] is False
