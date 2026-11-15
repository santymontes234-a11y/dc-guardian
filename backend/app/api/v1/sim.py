"""``/sim/*``: control the virtual ESP32 from the "Simulador" panel. Mounted only when
``DCG_SIMULATION=true``; admin role required. Never available in production."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Path
from pydantic import BaseModel, Field
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.api.deps import AdminCtx, AdminOnly, DbSession, ReadDb
from app.api.v1.kiosk import verify_frames
from app.core.config import get_settings
from app.core.errors import DomainError
from app.models import AccessSession, Engineer, RfidCard
from app.models.enums import AccessState, EngineerStatus
from app.services import biometrics
from app.sim import faces
from app.sim import service as sim

router = APIRouter(prefix="/sim", tags=["simulation"])
Code = Annotated[str, Path(pattern=r"^[A-Za-z0-9-]{2,30}$")]


class DistanceIn(BaseModel):
    distance_cm: float = Field(ge=0, le=400)


class SensorIn(BaseModel):
    ultrasonic: Literal["OK", "TIMEOUT"] = "OK"
    rfid: Literal["OK", "ERROR"] = "OK"


class OnlineIn(BaseModel):
    online: bool


class CardIn(BaseModel):
    uid: str = Field(min_length=1, max_length=40)


class FaceIn(BaseModel):
    mode: Literal["match", "other", "stranger"] = "match"


@router.get("/state")
def state(_: AdminOnly, db: ReadDb):
    cards = db.execute(select(RfidCard).order_by(RfidCard.id)).scalars().all()
    return {
        "devices": [d.state() for d in sim.all_doors()],
        "cards": [{"uid": c.uid, "label": c.label, "status": str(c.status),
                   "engineer": ({"id": c.engineer.id, "engineer_id": c.engineer.engineer_id,
                                 "full_name": c.engineer.full_name, "status": str(c.engineer.status)}
                                if c.engineer else None)} for c in cards],
        "face_frames": get_settings().face_frames,
    }


@router.post("/{device_code}/distance")
def set_distance(device_code: Code, body: DistanceIn, _: AdminOnly):
    vd = sim.door(device_code)
    out = sim.call(vd, lambda: vd.sim.set_distance(body.distance_cm), "presence")
    return {"device": vd.state(), "reply": out}


@router.post("/{device_code}/sensors")
def set_sensors(device_code: Code, body: SensorIn, _: AdminOnly):
    vd = sim.door(device_code)
    vd.sim.sensors = {"rfid": body.rfid, "ultrasonic": body.ultrasonic}
    out = sim.call(vd, vd.sim.heartbeat, "heartbeat")
    return {"device": vd.state(), "reply": out}


@router.post("/{device_code}/online")
def set_online(device_code: Code, body: OnlineIn, _: AdminOnly):
    """Unplug/plug the virtual ESP32. Unplugged: no heartbeats → OFFLINE after DCG_DEVICE_OFFLINE_S."""
    vd = sim.door(device_code)
    vd.online = body.online
    out = sim.call(vd, vd.sim.heartbeat, "heartbeat") if body.online else None
    return {"device": vd.state(), "reply": out}


@router.post("/{device_code}/heartbeat")
def heartbeat(device_code: Code, _: AdminOnly):
    vd = sim.door(device_code)
    return {"device": vd.state(), "reply": sim.call(vd, vd.sim.heartbeat, "heartbeat")}


@router.post("/{device_code}/card")
def card(device_code: Code, body: CardIn, _: AdminOnly):
    vd = sim.door(device_code)
    if not vd.sim.present:
        # Same rule as the firmware: without local presence the card read never reaches the backend.
        return {"device": vd.state(), "reply": {"action": "start", "error":
                "Sin presencia frente a la puerta: el ESP32 ignora la tarjeta (acércate primero)"}}
    out = sim.call(vd, lambda: vd.sim.start(body.uid), "start")
    return {"device": vd.state(), "reply": out}


@router.post("/{device_code}/face")
async def face(device_code: Code, body: FaceIn, ctx: AdminCtx):
    """Stand-in for the kiosk camera: sends N synthetic frames of the card holder ("match"),
    of another registered engineer ("other") or of an unregistered person ("stranger")."""
    vd = sim.door(device_code)
    sid = vd.sim.session_id
    if not sid:
        raise DomainError("SIM_NO_SESSION", "No hay ningún intento en curso en esta puerta", 409)
    seed = await run_in_threadpool(_face_seed, sid, body.mode)
    frames = faces.captures(seed, get_settings().face_frames, first_shot=hash(sid) % 1000)
    result = await run_in_threadpool(verify_frames, sid, frames, ctx)
    vd.last = {"action": f"face:{body.mode}", "status": 200, "data": result}
    return {"device": vd.state(), "reply": vd.last}


def _face_seed(session_id: str, mode: str) -> int:
    from app.db.session import ReadSessionLocal

    with ReadSessionLocal() as db:
        sess = db.get(AccessSession, session_id)
        if sess is None or sess.state != AccessState.AWAITING_FACE:
            raise DomainError("SESSION_NOT_AWAITING_FACE", "La sesión no está esperando verificación facial", 409)
        if mode == "match":
            return faces.engineer_seed(sess.engineer_id)
        if mode == "stranger":
            return faces.STRANGER_SEED
        other = db.execute(
            select(Engineer.id).where(Engineer.id != sess.engineer_id, Engineer.face_embedding_reference.is_not(None))
            .order_by(Engineer.id).limit(1)
        ).scalar_one_or_none()
        return faces.engineer_seed(other if other is not None else sess.engineer_id + 500)


@router.post("/{device_code}/poll")
def poll(device_code: Code, _: AdminOnly):
    """One decision poll; on a signed GRANTED the virtual servo opens (call /close afterwards)."""
    vd = sim.door(device_code)
    sid = vd.sim.session_id
    if not sid:
        raise DomainError("SIM_NO_SESSION", "No hay ningún intento en curso en esta puerta", 409)

    def run():
        r = vd.sim.poll(sid)
        open_ms = vd.sim.decide(r, sid)
        if open_ms is not None:
            vd.sim.opened(sid, open_ms)
        elif r.data.get("state") not in sim.esp32_sim.PENDING:
            vd.sim.session_id = None  # decided (denied / timeout): the attempt is over
        return r

    out = sim.call(vd, run, "poll")
    return {"device": vd.state(), "reply": out, "session_id": sid}


@router.post("/{device_code}/close")
def close(device_code: Code, _: AdminOnly):
    vd = sim.door(device_code)
    sid = vd.sim.session_id
    if not sid or vd.sim.door != "OPEN":
        raise DomainError("SIM_DOOR_NOT_OPEN", "La puerta virtual no está abierta", 409)
    out = sim.call(vd, lambda: vd.sim.closed(sid, "TIMER"), "closed")
    return {"device": vd.state(), "reply": out}


@router.post("/enroll-demo-faces")
def enroll_demo_faces(ctx: AdminCtx, db: DbSession):
    """Register a synthetic face for every ACTIVO engineer without one (so "match" works)."""
    s = get_settings()
    done = []
    pks = list(db.execute(
        select(Engineer.id).where(Engineer.status == EngineerStatus.ACTIVE,
                                  Engineer.face_embedding_reference.is_(None))
    ).scalars())
    db.rollback()
    for pk in pks:
        imgs = [(f"sim{i}.jpg", data) for i, data in
                enumerate(faces.captures(faces.engineer_seed(pk), s.face_enroll_min_samples, first_shot=500))]
        try:
            biometrics.enroll(db, ctx, pk, imgs, replace=False)
            done.append(pk)
        except DomainError as e:
            db.rollback()
            done.append({"engineer": pk, "error": e.code})
    return {"enrolled": done}
