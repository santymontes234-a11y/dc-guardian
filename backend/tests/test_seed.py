from app.core.security import decrypt_secret
from app.models import Device, Engineer, RfidCard
from app.services import audit
from scripts.seed import seed


def test_seed_is_idempotent_and_device_secret_is_encrypted(db):
    first = seed(db)
    db.commit()
    assert first["engineers"] == 3 and first["cards"] == 4 and first["device_secret"]

    device = db.query(Device).one()
    assert device.secret_encrypted != first["device_secret"]
    assert decrypt_secret(device.secret_encrypted) == first["device_secret"]

    second = seed(db)
    db.commit()
    assert second["engineers"] == 0 and second["cards"] == 0 and second["device_secret"] is None
    assert db.query(Engineer).count() == 3
    assert db.query(RfidCard).filter(RfidCard.engineer_id.is_(None)).count() == 1
    assert audit.verify_chain(db).ok
