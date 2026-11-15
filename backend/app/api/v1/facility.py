from fastapi import APIRouter, Response

from app.api.deps import AdminCtx, AdminOrAuditor, DbSession, ReadDb
from app.schemas.common import PathId
from app.schemas.facility import (
    AreaCreate,
    AreaOut,
    AreaUpdate,
    DeviceCreate,
    DeviceOut,
    DeviceUpdate,
    DeviceWithSecret,
)
from app.services import facility as svc

areas = APIRouter(prefix="/areas", tags=["areas"])
devices = APIRouter(prefix="/devices", tags=["devices"])


@areas.get("", response_model=list[AreaOut])
def list_areas(_: AdminOrAuditor, db: ReadDb):
    return svc.list_areas(db)


@areas.post("", response_model=AreaOut, status_code=201)
def create_area(body: AreaCreate, ctx: AdminCtx, db: DbSession):
    return svc.create_area(db, ctx, body)


@areas.patch("/{area_id}", response_model=AreaOut)
def update_area(area_id: PathId, body: AreaUpdate, ctx: AdminCtx, db: DbSession):
    return svc.update_area(db, ctx, area_id, body)


@areas.delete("/{area_id}", status_code=204)
def delete_area(area_id: PathId, ctx: AdminCtx, db: DbSession):
    svc.delete_area(db, ctx, area_id)
    return Response(status_code=204)


@devices.get("", response_model=list[DeviceOut])
def list_devices(_: AdminOrAuditor, db: ReadDb):
    return svc.list_devices(db)


@devices.post("", response_model=DeviceWithSecret, status_code=201)
def create_device(body: DeviceCreate, ctx: AdminCtx, db: DbSession):
    """Returns the HMAC secret **once**. It is stored encrypted and cannot be retrieved later."""
    dev, secret = svc.create_device(db, ctx, body)
    return DeviceWithSecret(device=dev, secret=secret)


@devices.get("/{device_id}", response_model=DeviceOut)
def get_device(device_id: PathId, _: AdminOrAuditor, db: ReadDb):
    return svc.get_device(db, device_id)


@devices.patch("/{device_id}", response_model=DeviceOut)
def update_device(device_id: PathId, body: DeviceUpdate, ctx: AdminCtx, db: DbSession):
    return svc.update_device(db, ctx, device_id, body)


@devices.post("/{device_id}/rotate-secret", response_model=DeviceWithSecret)
def rotate_device_secret(device_id: PathId, ctx: AdminCtx, db: DbSession):
    """Issues a new secret (shown once); the old one stops working immediately."""
    dev, secret = svc.rotate_secret(db, ctx, device_id)
    return DeviceWithSecret(device=dev, secret=secret)
