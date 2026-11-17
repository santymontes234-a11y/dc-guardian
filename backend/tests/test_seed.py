from app.core.security import decrypt_secret, encrypt_secret
from app.models import Area, Device, Engineer, RfidCard
from app.services import audit
from scripts.seed import seed


def test_seed_is_idempotent_and_device_secret_is_encrypted(db):
    first = seed(db)
    db.commit()
    assert first["engineers"] == 4 and first["cards"] == 5 and first["device_secret"]

    device = db.query(Device).one()
    assert device.secret_encrypted != first["device_secret"]
    assert decrypt_secret(device.secret_encrypted) == first["device_secret"]

    second = seed(db)
    db.commit()
    assert second["engineers"] == 0 and second["cards"] == 0 and second["device_secret"] is None
    assert second["adapted"] == 0
    assert db.query(Engineer).count() == 4
    assert db.query(RfidCard).filter(RfidCard.engineer_id.is_(None)).count() == 1
    assert audit.verify_chain(db).ok


def test_seed_telecom_conecta_scenario(db):
    seed(db)
    db.commit()
    areas = {a.code: a for a in db.query(Area)}
    assert areas["ENTRADA_PRINCIPAL"].name.startswith("Entrada principal")
    assert areas["SALA_SERVIDORES"].description == "Servidor de clientes"
    assert db.query(Device).one().area_id == areas["SALA_SERVIDORES"].id
    positions = {e.position for e in db.query(Engineer)}
    assert positions == {"Administrador de TI", "Ingeniero de red", "Personal de limpieza", "Proveedor"}


def test_seed_adapts_a_pre_telecom_database(db):
    """A database seeded before the scenario: old area code and old positions are adapted once."""
    old = Area(code="SALA-SERVIDORES", name="Sala de servidores", security_level=5, description="Racks")
    db.add(old)
    db.flush()
    db.add(Device(device_code="DC-DOOR-01", name="Puerta", area_id=old.id,
                  secret_encrypted=encrypt_secret("x" * 64)))
    db.add(Engineer(engineer_id="ENG-0001", full_name="Laura Méndez Ríos", department="Infraestructura",
                    position="Ingeniera de redes", institutional_email="laura.mendez@dcguardian.edu"))
    db.commit()

    out = seed(db)
    db.commit()
    assert out["adapted"] == 2 and out["device_secret"] is None
    codes = {a.code for a in db.query(Area)}
    assert "SALA-SERVIDORES" not in codes and {"SALA_SERVIDORES", "ENTRADA_PRINCIPAL"} <= codes
    assert db.query(Device).one().area.code == "SALA_SERVIDORES"
    assert db.query(Engineer).filter_by(engineer_id="ENG-0001").one().position == "Administrador de TI"
    assert seed(db)["adapted"] == 0
    db.commit()


def test_seed_never_gives_a_demo_card_to_a_real_engineer(db):
    db.add(Engineer(engineer_id="ENG-0004", full_name="Persona Real", department="Ops", position="Ingeniero",
                    institutional_email="real@dcguardian.edu"))
    db.commit()
    seed(db)
    db.commit()
    real = db.query(Engineer).filter_by(engineer_id="ENG-0004").one()
    assert real.position == "Ingeniero"
    assert db.query(RfidCard).filter_by(engineer_id=real.id).count() == 0
