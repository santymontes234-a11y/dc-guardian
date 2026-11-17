"""Access log ("bitácora", contract §6): one chronological view of every decided access attempt
in every zone, whatever the method.

Sources (no data is duplicated; rows are read from where they are decided):
- ``access_sessions`` → zone of the door's area, method ``RFID+ROSTRO`` (or ``BOTON_SALIDA``
  for the inside exit button). Undecided sessions (still waiting for the face) are omitted.
- ``entrance_events`` → zone ``ENTRADA_PRINCIPAL``, method ``QR``.

Row: ``{id, source, at, person, engineer_id, position, zone:{code,name}, method, direction,
result, reason_code, reason, device_code}`` with ``result`` ``GRANTED``/``DENIED``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, func, literal, select, union_all
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AccessSession, Area, Device, Engineer, EntranceEvent
from app.models.enums import AccessDirection, AccessState
from app.schemas.common import PageParams
from app.services import access_engine as engine

METHOD_QR = "QR"
METHOD_RFID_FACE = "RFID+ROSTRO"
METHOD_EXIT_BUTTON = "BOTON_SALIDA"
METHODS = (METHOD_QR, METHOD_RFID_FACE, METHOD_EXIT_BUTTON)
RESULTS = ("GRANTED", "DENIED")
_GRANTED_STATES = (AccessState.GRANTED, AccessState.OPENED, AccessState.CLOSED)

SRC_SESSION, SRC_ENTRANCE = "access_session", "entrance_event"


def _union():
    sessions = (
        select(
            literal(SRC_SESSION).label("source"),
            AccessSession.id.label("id"),
            AccessSession.created_at.label("at"),
            case((AccessSession.card_uid_raw == engine.BUTTON_UID, literal(METHOD_EXIT_BUTTON)),
                 else_=literal(METHOD_RFID_FACE)).label("method"),
            case((AccessSession.state.in_(_GRANTED_STATES), literal("GRANTED")),
                 else_=literal("DENIED")).label("result"),
            Device.area_id.label("area_id"),
            AccessSession.engineer_id.label("engineer_id"),
        )
        .join(Device, Device.id == AccessSession.device_id)
        .where(AccessSession.state.not_in(engine.PENDING_STATES))
    )
    entrance = select(
        literal(SRC_ENTRANCE).label("source"),
        EntranceEvent.id.label("id"),
        EntranceEvent.created_at.label("at"),
        EntranceEvent.method.label("method"),
        EntranceEvent.result.label("result"),
        EntranceEvent.area_id.label("area_id"),
        EntranceEvent.engineer_id.label("engineer_id"),
    )
    return union_all(sessions, entrance).subquery("log")


def list_(db: Session, page: PageParams, *, method: str | None = None, result: str | None = None,
          zone: str | None = None, engineer_id: int | None = None, since: datetime | None = None,
          until: datetime | None = None) -> tuple[list[dict], int]:
    log = _union()
    stmt = select(log.c.source, log.c.id, log.c.at)
    if method:
        stmt = stmt.where(log.c.method == method)
    if result:
        stmt = stmt.where(log.c.result == result)
    if zone:
        area_id = db.execute(select(Area.id).where(Area.code == zone.upper())).scalar_one_or_none()
        if area_id is None:
            return [], 0
        stmt = stmt.where(log.c.area_id == area_id)
    if engineer_id:
        stmt = stmt.where(log.c.engineer_id == engineer_id)
    if since:
        stmt = stmt.where(log.c.at >= since)
    if until:
        stmt = stmt.where(log.c.at < until)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    keys = db.execute(stmt.order_by(log.c.at.desc(), log.c.id.desc()).limit(page.limit).offset(page.offset)).all()
    rows: list[dict] = []
    for source, id_, _ in keys:
        if source == SRC_SESSION:
            sess = db.get(AccessSession, id_)
            if sess is not None:
                rows.append(session_row(db, sess))
        else:
            ev = db.get(EntranceEvent, id_)
            if ev is not None:
                rows.append(entrance_row(db, ev))
    return rows, total


def _person(eng: Engineer | None) -> dict:
    return {"person": eng.full_name if eng else None, "engineer_id": eng.engineer_id if eng else None,
            "position": eng.position if eng else None}


def _zone(area: Area | None, fallback_code: str | None = None) -> dict:
    if area is not None:
        return {"code": area.code, "name": area.name}
    return {"code": fallback_code, "name": None}


def session_row(db: Session, sess: AccessSession) -> dict:
    dev = db.get(Device, sess.device_id)
    area = db.get(Area, dev.area_id) if dev else None
    eng = db.get(Engineer, sess.engineer_id) if sess.engineer_id else None
    granted = sess.state in _GRANTED_STATES
    return {
        "id": sess.id, "source": SRC_SESSION, "at": sess.created_at.isoformat(), **_person(eng),
        "zone": _zone(area),
        "method": METHOD_EXIT_BUTTON if engine.is_button_exit(sess) else METHOD_RFID_FACE,
        "direction": str(sess.direction), "result": "GRANTED" if granted else "DENIED",
        "reason_code": None if granted else sess.reason_code,
        "reason": None if granted else engine.reason_text(sess.reason_code),
        "device_code": dev.device_code if dev else None,
    }


def entrance_row(db: Session, ev: EntranceEvent, *, area: Area | None = None, device: Device | None = None,
                 engineer: Engineer | None = None) -> dict:
    area = area if area is not None else (db.get(Area, ev.area_id) if ev.area_id else None)
    dev = device if device is not None else (db.get(Device, ev.device_id) if ev.device_id else None)
    eng = engineer if engineer is not None else (db.get(Engineer, ev.engineer_id) if ev.engineer_id else None)
    return {
        "id": ev.id, "source": SRC_ENTRANCE, "at": ev.created_at.isoformat(), **_person(eng),
        "zone": _zone(area, get_settings().entrance_area_code), "method": ev.method,
        "direction": str(AccessDirection.ENTRY), "result": ev.result, "reason_code": ev.reason_code,
        "reason": engine.reason_text(ev.reason_code), "device_code": dev.device_code if dev else None,
    }
