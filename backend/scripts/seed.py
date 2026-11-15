"""Load demo data: areas, one door device, engineers and RFID cards.

Usage: python -m scripts.seed
Idempotent: existing rows (matched by their unique code) are left untouched.
The device secret is printed ONCE when the device is created; copy it to the ESP32 config.
Admins are not seeded (use scripts.create_admin).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import encrypt_secret, generate_device_secret
from app.db.session import SessionLocal
from app.db.types import utcnow
from app.models import Area, Device, Engineer, RfidCard
from app.models.enums import ActorType
from app.services import audit

AREAS = [
    ("SALA-SERVIDORES", "Sala de servidores", 5, "Racks de cómputo y almacenamiento"),
    ("NOC", "Centro de operaciones de red", 4, "Monitoreo 24/7"),
    ("ENERGIA", "Sala de energía y UPS", 4, "Tableros, UPS y baterías"),
]

ENGINEERS = [
    # code, name, department, position, email, card uid
    ("ENG-0001", "Laura Méndez Ríos", "Infraestructura", "Ingeniera de redes", "laura.mendez@dcguardian.edu", "04A1B2C3"),
    ("ENG-0002", "Carlos Ortega Vidal", "Operaciones", "Ingeniero de sistemas", "carlos.ortega@dcguardian.edu", "93F2A1D7"),
    ("ENG-0003", "Ana Torres Gil", "Energía", "Ingeniera eléctrica", "ana.torres@dcguardian.edu", "5B7C9E01"),
]


def _get_or_create(db: Session, model, where, **values):
    obj = db.execute(select(model).filter_by(**where)).scalar_one_or_none()
    if obj:
        return obj, False
    obj = model(**where, **values)
    db.add(obj)
    db.flush()
    return obj, True


def seed(db: Session) -> dict:
    created: dict = {"areas": 0, "engineers": 0, "cards": 0, "device_secret": None}

    areas = {}
    for code, name, level, desc in AREAS:
        area, new = _get_or_create(db, Area, {"code": code}, name=name, security_level=level, description=desc)
        areas[code] = area
        created["areas"] += new

    secret = generate_device_secret()
    _, new = _get_or_create(
        db, Device, {"device_code": "DC-DOOR-01"},
        name="Puerta principal sala de servidores",
        area_id=areas["SALA-SERVIDORES"].id,
        secret_encrypted=encrypt_secret(secret),
        presence_threshold_cm=50,
        door_open_ms=5000,
    )
    if new:
        created["device_secret"] = secret

    for code, name, dept, pos, email, uid in ENGINEERS:
        eng, new = _get_or_create(db, Engineer, {"engineer_id": code},
                                  full_name=name, department=dept, position=pos, institutional_email=email)
        created["engineers"] += new
        _, new = _get_or_create(db, RfidCard, {"uid": uid}, engineer_id=eng.id, assigned_at=utcnow(),
                                label=f"Tarjeta {code}")
        created["cards"] += new

    # One unassigned card to demo the "UNKNOWN / NOT LINKED" paths.
    _, new = _get_or_create(db, RfidCard, {"uid": "DEADBEEF"}, label="Tarjeta sin asignar")
    created["cards"] += new

    audit.record(db, action="system.seed", actor_type=ActorType.SYSTEM,
                 details={k: v for k, v in created.items() if k != "device_secret"})
    return created


def main() -> None:
    with SessionLocal() as db:
        result = seed(db)
        db.commit()
    print(f"Áreas nuevas: {result['areas']} · Ingenieros nuevos: {result['engineers']} · "
          f"Tarjetas nuevas: {result['cards']}")
    if result["device_secret"]:
        print("\nDispositivo DC-DOOR-01 creado. Secreto HMAC (se muestra solo esta vez):")
        print(f"  {result['device_secret']}")
        print("Cópialo en firmware/esp32-door/include/dcg_config.h (DCG_DEVICE_SECRET).")


if __name__ == "__main__":
    main()
