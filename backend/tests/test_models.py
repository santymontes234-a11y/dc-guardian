from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, StatementError

from app.models import Area, AuthorizationRequest, Engineer, RfidCard, normalize_uid
from app.models.enums import RequestStatus


def _engineer(db, code="ENG-9000"):
    e = Engineer(engineer_id=code, full_name="Prueba", department="TI", position="Ing.",
                 institutional_email=f"{code.lower()}@x.edu")
    db.add(e)
    db.flush()
    return e


def _request(db, start, minutes=60, status=RequestStatus.APPROVED):
    eng = _engineer(db)
    card = RfidCard(uid="AABBCCDD", engineer_id=eng.id)
    area = Area(code="A1", name="Área 1")
    db.add_all([card, area])
    db.flush()
    req = AuthorizationRequest(engineer_id=eng.id, card_id=card.id, area_id=area.id, reason="Mantenimiento",
                               start_at=start, duration_minutes=minutes,
                               end_at=AuthorizationRequest.compute_end(start, minutes), status=status)
    db.add(req)
    db.commit()
    return req


def test_engineer_registration_does_not_imply_authorization(db):
    eng = _engineer(db)
    db.commit()
    assert db.query(AuthorizationRequest).filter_by(engineer_id=eng.id).count() == 0
    # Registro 1 exposes no access-granting field.
    assert not {"authorized", "access_granted", "card_uid"} & set(Engineer.__table__.columns.keys())


def test_datetimes_roundtrip_as_aware_utc(db):
    start = datetime(2026, 11, 14, 15, 0, tzinfo=UTC)
    req = _request(db, start)
    db.expire_all()
    loaded = db.get(AuthorizationRequest, req.id)
    assert loaded.start_at == start and loaded.start_at.tzinfo is not None
    assert loaded.end_at - loaded.start_at == timedelta(minutes=60)


def test_naive_datetime_rejected(db):
    with pytest.raises(StatementError):
        _request(db, datetime(2026, 11, 14, 15, 0))


def test_is_in_force_window(db):
    start = datetime(2026, 11, 14, 15, 0, tzinfo=UTC)
    req = _request(db, start, minutes=30)
    assert not req.is_in_force(start - timedelta(seconds=1))
    assert req.is_in_force(start)
    assert req.is_in_force(start + timedelta(minutes=29))
    assert not req.is_in_force(start + timedelta(minutes=30))


def test_pending_request_is_not_in_force(db):
    start = datetime(2026, 11, 14, 15, 0, tzinfo=UTC)
    req = _request(db, start, status=RequestStatus.PENDING)
    assert not req.is_in_force(start + timedelta(minutes=1))


def test_invalid_status_value_rejected_by_db(db):
    eng = _engineer(db)
    db.commit()
    # Bypass the ORM on purpose: the CHECK constraint must hold even for raw SQL.
    with pytest.raises(IntegrityError):
        db.execute(text("UPDATE engineers SET status='HACKEADO' WHERE id=:id"), {"id": eng.id})
        db.commit()


def test_duration_constraint(db):
    with pytest.raises(IntegrityError):
        _request(db, datetime(2026, 11, 14, 15, 0, tzinfo=UTC), minutes=0)


def test_card_uid_unique(db):
    db.add(RfidCard(uid="01020304"))
    db.commit()
    db.add(RfidCard(uid="01020304"))
    with pytest.raises(IntegrityError):
        db.commit()


@pytest.mark.parametrize("raw,expected", [("04:a1:b2:c3", "04A1B2C3"), ("04 A1 B2 C3", "04A1B2C3"), ("deadbeef", "DEADBEEF")])
def test_normalize_uid(raw, expected):
    assert normalize_uid(raw) == expected


@pytest.mark.parametrize("raw", ["", "XYZ", "04A1'; DROP", "0" * 21])
def test_normalize_uid_rejects_garbage(raw):
    with pytest.raises(ValueError):
        normalize_uid(raw)
