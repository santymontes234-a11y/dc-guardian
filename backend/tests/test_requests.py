from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.errors import DomainError
from app.db.types import utcnow
from app.models import AuditLog, AuthorizationRequest
from app.models.enums import ActorType, RequestStatus
from app.schemas.requests import RequestCreate
from app.services import audit
from app.services import requests as svc
from app.services.context import ActorCtx

REQ = "/api/v1/requests"
S = RequestStatus


def _approve(f, req, **kw):
    return f.ok("POST", f"{REQ}/{req['id']}/approve", json=kw)


# ----------------------------------------------------------------- creation rules
def test_create_pending_request(f):
    eng, card, area = f.setup()
    req = f.request(eng, card, area, minutes=90)
    assert req["status"] == "PENDIENTE" and req["in_force"] is False
    assert req["creator"]["username"] == "admin" and req["reviewer"] is None
    assert req["engineer"]["engineer_id"] == eng["engineer_id"] and req["card"]["uid"] == card["uid"]


def test_card_must_be_linked_to_engineer(f):
    eng, _, area = f.setup()
    foreign = f.card(f.engineer()["id"])
    r = f.request(eng, foreign, area, expected=409)
    assert r["error"]["code"] == "CARD_NOT_LINKED"
    unassigned = f.card()
    assert f.request(eng, unassigned, area, expected=409)["error"]["code"] == "CARD_NOT_LINKED"


def test_engineer_must_be_active(f):
    eng, card, area = f.setup()
    f.ok("POST", f"/api/v1/engineers/{eng['id']}/status", json={"status": "INACTIVO", "reason": "Fin contrato"})
    assert f.request(eng, card, area, expected=409)["error"]["code"] == "ENGINEER_NOT_ACTIVE"


def test_time_rules(f):
    eng, card, area = f.setup()
    past = utcnow() - timedelta(hours=1)
    assert f.request(eng, card, area, start=past, expected=422)["error"]["code"] == "START_IN_PAST"
    far = utcnow() + timedelta(days=365)
    assert f.request(eng, card, area, start=far, expected=422)["error"]["code"] == "START_TOO_FAR"
    naive = (utcnow() + timedelta(hours=1)).replace(tzinfo=None)
    assert f.request(eng, card, area, start=naive, expected=422)["error"]["code"] == "VALIDATION_ERROR"
    assert f.request(eng, card, area, minutes=0, expected=422)["error"]["code"] == "VALIDATION_ERROR"
    assert f.request(eng, card, area, minutes=1441, expected=422)["error"]["code"] == "VALIDATION_ERROR"
    # starting "now" (within grace) is fine
    f.request(eng, card, area, start=utcnow() - timedelta(minutes=1))


def test_overlap_same_card_and_area(f):
    eng, card, area = f.setup()
    start = utcnow() + timedelta(hours=1)
    f.request(eng, card, area, start=start, minutes=60)
    clash = f.request(eng, card, area, start=start + timedelta(minutes=30), expected=409)
    assert clash["error"]["code"] == "REQUEST_OVERLAP"
    f.request(eng, card, area, start=start + timedelta(minutes=60))  # back-to-back is fine
    f.request(eng, card, f.area(), start=start)  # other area is fine


# ----------------------------------------------------------------- state machine
def test_approve_records_reviewer(f):
    eng, card, area = f.setup()
    req = _approve(f, f.request(eng, card, area), notes="OK turno noche")
    assert req["status"] == "APROBADA"
    assert req["reviewer"]["username"] == "admin" and req["reviewed_at"] and req["review_notes"] == "OK turno noche"


def test_reject_requires_notes(f):
    eng, card, area = f.setup()
    req = f.request(eng, card, area)
    assert f.c.post(f"{REQ}/{req['id']}/reject", json={}).status_code == 422
    out = f.ok("POST", f"{REQ}/{req['id']}/reject", json={"notes": "Sin justificación"})
    assert out["status"] == "RECHAZADA" and out["reviewer"]["username"] == "admin"


def test_revoke_keeps_approver(f):
    eng, card, area = f.setup()
    req = _approve(f, f.request(eng, card, area), notes="aprobada")
    out = f.ok("POST", f"{REQ}/{req['id']}/revoke", json={"notes": "Incidente de seguridad"})
    assert out["status"] == "REVOCADA"
    assert out["review_notes"] == "aprobada" and out["reviewer"]["username"] == "admin"
    assert out["closer"]["username"] == "admin" and out["close_notes"] == "Incidente de seguridad"


@pytest.mark.parametrize("first,then", [
    ("reject", "approve"), ("reject", "revoke"), ("approve", "approve"), ("approve", "reject"),
    ("revoke", "approve"), ("finalize", "revoke"),
])
def test_invalid_transitions(f, first, then):
    eng, card, area = f.setup()
    req = f.request(eng, card, area)
    if first in ("revoke", "finalize"):
        _approve(f, req)
    f.ok("POST", f"{REQ}/{req['id']}/{first}", json={"notes": "motivo"})
    r = f.c.post(f"{REQ}/{req['id']}/{then}", json={"notes": "motivo"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_TRANSITION"


def test_pending_cannot_be_revoked_or_finalized(f):
    eng, card, area = f.setup()
    req = f.request(eng, card, area)
    assert f.c.post(f"{REQ}/{req['id']}/revoke", json={"notes": "x" * 5}).status_code == 409
    assert f.c.post(f"{REQ}/{req['id']}/finalize", json={}).status_code == 409


def test_terminal_states_have_no_exits():
    for st in (S.REJECTED, S.EXPIRED, S.REVOKED, S.FINISHED):
        assert svc.TRANSITIONS[st] == frozenset()
    assert set(svc.TRANSITIONS) == set(S)


def test_approve_revalidates_parties(f):
    eng, card, area = f.setup()
    req = f.request(eng, card, area)
    f.ok("POST", f"/api/v1/cards/{card['id']}/status", json={"status": "BLOQUEADA", "reason": "Revisión"})
    r = f.c.post(f"{REQ}/{req['id']}/approve", json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "CARD_NOT_ACTIVE"


# ----------------------------------------------------------------- time-driven behaviour
def _service_request(db, admin_id, start, minutes=30):
    """Create a request as if 'now' were ``start`` (bypasses the start-in-past rule)."""
    from app.models import Area, Engineer, RfidCard

    eng = Engineer(engineer_id="ENG-5000", full_name="Tiempo", department="TI", position="Ing",
                   institutional_email="t@dcguardian.edu")
    db.add(eng)
    db.flush()
    card = RfidCard(uid="CAFEBABE", engineer_id=eng.id)
    area = Area(code="T1", name="T1")
    db.add_all([card, area])
    db.commit()
    ctx = ActorCtx(ActorType.ADMIN, admin_id, now=start)
    req = svc.create(db, ctx, RequestCreate(engineer_id=eng.id, card_id=card.id, area_id=area.id,
                                            reason="Prueba de tiempo", start_at=start, duration_minutes=minutes))
    return req, ctx


def test_approving_after_window_marks_expired(db, admin):
    start = utcnow() - timedelta(hours=2)
    req, _ = _service_request(db, admin.id, start)
    with pytest.raises(DomainError) as exc:
        svc.approve(db, ActorCtx(ActorType.ADMIN, admin.id), req.id, None)
    assert exc.value.code == "REQUEST_WINDOW_PASSED"
    assert svc.get(db, req.id).status == S.EXPIRED


def test_in_force_window_and_lookup(db, admin):
    start = utcnow() + timedelta(hours=1)
    req, ctx = _service_request(db, admin.id, start, minutes=30)
    svc.approve(db, ctx, req.id, None)
    assert svc.find_in_force(db, req.card_id, req.area_id, start - timedelta(seconds=1)) is None
    assert svc.find_in_force(db, req.card_id, req.area_id, start).id == req.id
    assert svc.find_in_force(db, req.card_id, req.area_id, start + timedelta(minutes=30)) is None
    # wrong area never matches
    assert svc.find_in_force(db, req.card_id, req.area_id + 99, start) is None


def test_sweep_expires_and_finishes(db, admin):
    start = utcnow() + timedelta(minutes=10)
    pending, ctx = _service_request(db, admin.id, start, minutes=30)

    unused = svc.create(db, ctx, RequestCreate(engineer_id=pending.engineer_id, card_id=pending.card_id,
                                               area_id=pending.area_id, reason="Sin uso",
                                               start_at=start + timedelta(hours=1), duration_minutes=30))
    used = svc.create(db, ctx, RequestCreate(engineer_id=pending.engineer_id, card_id=pending.card_id,
                                             area_id=pending.area_id, reason="Con uso",
                                             start_at=start + timedelta(hours=2), duration_minutes=30))
    svc.approve(db, ctx, unused.id, None)
    svc.approve(db, ctx, used.id, None)
    row = db.get(AuthorizationRequest, used.id)
    row.use_count = 1  # the access engine (F5) will do this
    db.commit()

    # Nothing to do before the windows end
    assert svc.sweep(db, ActorCtx.system(now=start + timedelta(minutes=5))) == {"expired": 0, "finished": 0}

    later = start + timedelta(hours=3)
    assert svc.sweep(db, ActorCtx.system(now=later)) == {"expired": 2, "finished": 1}
    assert svc.get(db, pending.id).status == S.EXPIRED
    assert svc.get(db, unused.id).status == S.EXPIRED
    finished = svc.get(db, used.id)
    assert finished.status == S.FINISHED and finished.closed_by is None  # closed by the system
    assert finished.reviewed_by == admin.id  # approver kept
    # idempotent
    assert svc.sweep(db, ActorCtx.system(now=later)) == {"expired": 0, "finished": 0}

    sys_entries = db.execute(
        select(AuditLog).where(AuditLog.actor_type == ActorType.SYSTEM, AuditLog.action.like("request.%"))
    ).scalars().all()
    assert len(sys_entries) == 3
    assert audit.verify_chain(db).ok


def test_in_force_filter_via_api(f):
    eng, card, area = f.setup()
    now_req = _approve(f, f.request(eng, card, area, start=utcnow() - timedelta(minutes=1)))
    f.request(eng, card, area, start=utcnow() + timedelta(hours=5))
    page = f.ok("GET", REQ, params={"in_force": True})
    assert [r["id"] for r in page["items"]] == [now_req["id"]]
    assert page["items"][0]["in_force"] is True
    assert f.ok("GET", REQ, params={"status": "PENDIENTE"})["total"] == 1


def test_audit_api_lists_request_lifecycle(f, auditor_api):
    eng, card, area = f.setup()
    req = f.request(eng, card, area)
    _approve(f, req)
    page = auditor_api.get("/api/v1/audit", params={"action": "request.", "entity_id": str(req["id"])}).json()
    assert [e["action"] for e in page["items"]] == ["request.approved", "request.created"]
    assert page["items"][0]["details"]["to"] == "APROBADA"
    assert auditor_api.get("/api/v1/audit/verify").json()["ok"] is True
