"""Areas and door devices."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import DomainError, not_found
from app.core.security import encrypt_secret, generate_device_secret
from app.models import AccessSession, Area, AuthorizationRequest, Device
from app.models.enums import DeviceStatus
from app.schemas.facility import AreaCreate, AreaUpdate, DeviceCreate, DeviceUpdate
from app.services.context import ActorCtx, diff_fields


# ----------------------------------------------------------------- areas
def get_area(db: Session, area_id: int) -> Area:
    area = db.get(Area, area_id, populate_existing=True)
    if area is None:
        raise not_found("AREA_NOT_FOUND", "Área no encontrada")
    return area


def list_areas(db: Session) -> list[Area]:
    return list(db.execute(select(Area).order_by(Area.code)).scalars())


def create_area(db: Session, ctx: ActorCtx, data: AreaCreate) -> Area:
    if db.execute(select(Area.id).where(Area.code == data.code)).first():
        raise DomainError("AREA_CODE_TAKEN", "Ya existe un área con ese código", 409)
    area = Area(**data.model_dump())
    db.add(area)
    db.flush()
    ctx.audit(db, "area.created", "area", area.id, {"code": area.code})
    db.commit()
    return area


def update_area(db: Session, ctx: ActorCtx, area_id: int, data: AreaUpdate) -> Area:
    area = get_area(db, area_id)
    diff = diff_fields(area, data.model_dump(exclude_unset=True, exclude_none=True))
    if diff:
        ctx.audit(db, "area.updated", "area", area.id, {"changes": diff})
        db.commit()
    return area


def delete_area(db: Session, ctx: ActorCtx, area_id: int) -> None:
    area = get_area(db, area_id)
    used = (
        db.execute(select(Device.id).where(Device.area_id == area.id).limit(1)).first()
        or db.execute(select(AuthorizationRequest.id).where(AuthorizationRequest.area_id == area.id).limit(1)).first()
    )
    if used:
        raise DomainError("AREA_IN_USE", "El área tiene dispositivos o solicitudes asociadas", 409)
    ctx.audit(db, "area.deleted", "area", area.id, {"code": area.code})
    db.delete(area)
    db.commit()


# ----------------------------------------------------------------- devices
def get_device(db: Session, device_id: int) -> Device:
    dev = db.get(Device, device_id, options=[selectinload(Device.area)], populate_existing=True)
    if dev is None:
        raise not_found("DEVICE_NOT_FOUND", "Dispositivo no encontrado")
    return dev


def list_devices(db: Session) -> list[Device]:
    return list(db.execute(select(Device).options(selectinload(Device.area)).order_by(Device.device_code)).scalars())


def create_device(db: Session, ctx: ActorCtx, data: DeviceCreate) -> tuple[Device, str]:
    if db.execute(select(Device.id).where(Device.device_code == data.device_code)).first():
        raise DomainError("DEVICE_CODE_TAKEN", "Ya existe un dispositivo con ese código", 409)
    get_area(db, data.area_id)
    secret = generate_device_secret()
    dev = Device(**data.model_dump(), secret_encrypted=encrypt_secret(secret), status=DeviceStatus.OFFLINE)
    db.add(dev)
    db.flush()
    ctx.audit(db, "device.created", "device", dev.id, {"device_code": dev.device_code, "area_id": dev.area_id})
    db.commit()
    return get_device(db, dev.id), secret


def update_device(db: Session, ctx: ActorCtx, device_id: int, data: DeviceUpdate) -> Device:
    dev = get_device(db, device_id)
    changes = data.model_dump(exclude_unset=True, exclude_none=True)
    enabled = changes.pop("enabled", None)
    if "area_id" in changes:
        get_area(db, changes["area_id"])
        busy = db.execute(
            select(func.count()).select_from(AccessSession)
            .where(AccessSession.device_id == dev.id, AccessSession.decided_at.is_(None))
        ).scalar_one()
        if busy:
            raise DomainError("DEVICE_BUSY", "El dispositivo tiene un intento de acceso en curso", 409)
    if enabled is not None:
        if not enabled:
            changes["status"] = DeviceStatus.DISABLED
        elif dev.status == DeviceStatus.DISABLED:
            changes["status"] = DeviceStatus.OFFLINE  # back online on next heartbeat
    diff = diff_fields(dev, changes)
    if diff:
        ctx.audit(db, "device.updated", "device", dev.id, {"changes": diff})
        db.commit()
    return get_device(db, dev.id)


def rotate_secret(db: Session, ctx: ActorCtx, device_id: int) -> tuple[Device, str]:
    dev = get_device(db, device_id)
    secret = generate_device_secret()
    dev.secret_encrypted = encrypt_secret(secret)
    ctx.audit(db, "device.secret_rotated", "device", dev.id)
    db.commit()
    return get_device(db, dev.id), secret
