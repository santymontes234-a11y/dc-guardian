from fastapi import APIRouter

from app.api.v1 import (
    audit,
    auth,
    cards,
    device_gateway,
    engineers,
    facility,
    kiosk,
    monitoring,
    requests,
    system,
    vision,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(system.router)
api_router.include_router(auth.router)
api_router.include_router(engineers.router)
api_router.include_router(vision.router)
api_router.include_router(kiosk.vision_verify)
api_router.include_router(kiosk.kiosk)
api_router.include_router(cards.router)
api_router.include_router(facility.areas)
# Must precede facility.devices so "/devices/status/all" is not captured by "/devices/{device_id}".
api_router.include_router(monitoring.hardware)
api_router.include_router(facility.devices)
api_router.include_router(requests.router)
api_router.include_router(audit.router)
api_router.include_router(monitoring.sessions)
api_router.include_router(monitoring.alerts)
api_router.include_router(monitoring.stats)
api_router.include_router(monitoring.system)
api_router.include_router(monitoring.access_log)
api_router.include_router(monitoring.environment)
api_router.include_router(device_gateway.router)
