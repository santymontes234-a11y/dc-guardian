"""Load demo data (scenario «Telecom Conecta»): areas, one door device, engineers and RFID cards.

Usage: python -m scripts.seed
Idempotent: existing rows (matched by their unique code) are left untouched, except for the
one-time adaptation of databases seeded before the Telecom Conecta scenario (area
``SALA-SERVIDORES`` → ``SALA_SERVIDORES``; demo engineers that still have their old position
get the new one).
The device secret is printed ONCE when the device is created; copy it to the ESP32 config.
Admins, QR credentials and authorization requests are not seeded (Registro 2 is always an
explicit admin decision).
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

SERVER_ROOM = "SALA_SERVIDORES"
ENTRANCE = "ENTRADA_PRINCIPAL"

AREAS = [
    # code, name, security level, description
    (ENTRANCE, "Entrada principal / recepción", 2, "Acceso con código QR (webcam en recepción) → LED verde"),
    (SERVER_ROOM, "Sala de servidores", 5, "Servidor de clientes"),
    ("NOC", "Centro de operaciones de red", 4, "Monitoreo 24/7"),
    ("ENERGIA", "Sala de energía y UPS", 4, "Tableros, UPS y baterías"),
]
LEGACY_AREA_CODES = {"SALA-SERVIDORES": SERVER_ROOM}

ENGINEERS = [
    # code, name, department, position, email, card uid
    ("ENG-0001", "Laura Méndez Ríos", "Tecnologías de la información", "Administrador de TI",
     "laura.mendez@dcguardian.edu", "04A1B2C3"),
    ("ENG-0002", "Carlos Ortega Vidal", "Redes y telecomunicaciones", "Ingeniero de red",
     "carlos.ortega@dcguardian.edu", "93F2A1D7"),
    ("ENG-0003", "Ana Torres Gil", "Servicios generales", "Personal de limpieza",
     "ana.torres@dcguardian.edu", "5B7C9E01"),
    ("ENG-0004", "Miguel Paredes Soto", "Proveedor externo", "Proveedor",
     "miguel.paredes@dcguardian.edu", "7E3D2C1B"),
]
# Positions of the pre-Telecom-Conecta seed: only these are updated in existing databases.
LEGACY_POSITIONS = {"Ingeniera de redes", "Ingeniero de sistemas", "Ingeniera eléctrica"}


def _get_or_create(db: Session, model, where, **values):
    obj = db.execute(select(model).filter_by(**where)).scalar_one_or_none()
    if obj:
        return obj, False
    obj = model(**where, **values)
    db.add(obj)
    db.flush()
    return obj, True


def _adapt_legacy(db: Session) -> int:
    """Bring a database seeded before the Telecom Conecta scenario up to date (idempotent)."""
    n = 0
    for old, new in LEGACY_AREA_CODES.items():
        area = db.execute(select(Area).filter_by(code=old)).scalar_one_or_none()
        if area is not None and db.execute(select(Area.id).filter_by(code=new)).first() is None:
            area.code = new
            area.description = "Servidor de clientes"
            n += 1
    for code, _name, dept, pos, _email, _uid in ENGINEERS:
        eng = db.execute(select(Engineer).filter_by(engineer_id=code)).scalar_one_or_none()
        if eng is not None and eng.position in LEGACY_POSITIONS:
            eng.position, eng.department = pos, dept
            n += 1
    db.flush()
    return n


def seed(db: Session) -> dict:
    created: dict = {"areas": 0, "engineers": 0, "cards": 0, "device_secret": None, "adapted": 0}

    created["adapted"] = _adapt_legacy(db)
    areas = {}
    for code, name, level, desc in AREAS:
        area, new = _get_or_create(db, Area, {"code": code}, name=name, security_level=level, description=desc)
        areas[code] = area
        created["areas"] += new

    secret = generate_device_secret()
    _, new = _get_or_create(
        db, Device, {"device_code": "DC-DOOR-01"},
        name="Puerta sala de servidores + LED entrada principal",
        area_id=areas[SERVER_ROOM].id,
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
        if eng.institutional_email != email:
            continue  # that ENG code belongs to a real engineer created later: never give them a demo card
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
          f"Tarjetas nuevas: {result['cards']} · Registros adaptados: {result['adapted']}")
    if result["device_secret"]:
        print("\nDispositivo DC-DOOR-01 creado. Secreto HMAC (se muestra solo esta vez):")
        print(f"  {result['device_secret']}")
        print("Cópialo en firmware/esp32-door/include/dcg_config.h (DCG_DEVICE_SECRET).")


if __name__ == "__main__":
    main()
