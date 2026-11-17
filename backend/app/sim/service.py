"""Virtual ESP32 doors driven from the web "Simulador" panel (DCG_SIMULATION=true only).

Each virtual door is a ``simulator/esp32_sim.Esp32Sim`` that sends **real signed HTTP
requests** to this backend (``DCG_SIM_BASE_URL``), so the panel exercises the exact gateway,
HMAC and anti-replay path the physical ESP32 uses. The device secret is read (decrypted) from
the database, which is acceptable only because simulation mode is a local demo.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
import threading
from collections.abc import Callable
from typing import Any

from sqlalchemy import select

from app.core.config import PROJECT_ROOT, get_settings
from app.core.errors import DomainError
from app.core.security import decrypt_secret
from app.db.session import SessionLocal
from app.models import Device

log = logging.getLogger(__name__)


def _load_sim_module():
    name = "dcg_esp32_sim"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / "simulator" / "esp32_sim.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


esp32_sim = _load_sim_module()

# Overridable in tests: returns the transport the virtual devices use.
transport_factory: Callable[[], Any] = lambda: esp32_sim.UrllibTransport(get_settings().sim_base_url)  # noqa: E731


class VirtualDoor:
    def __init__(self, device_code: str, secret: str):
        self.sim = esp32_sim.Esp32Sim(device_code, secret, transport_factory(), fw="sim-panel-1.0")
        self.online = True  # False = "unplugged": no heartbeats, every call fails
        self.lock = threading.Lock()
        self.last: dict | None = None  # last reply, for the panel

    def state(self) -> dict:
        s = self.sim
        return {"device_code": s.device_id, "online": self.online, "distance_cm": s.distance_cm,
                "threshold_cm": s.threshold_cm, "present": s.present, "door": s.door, "sensors": dict(s.sensors),
                "session_id": s.session_id, "door_open_ms": s.door_open_ms, "last": self.last,
                # Main entrance LED + DHT11 (contrato-qr-dht11.md §5). getattr: older simulators lack them.
                "entrance_led": getattr(s, "entrance_led", None), "fan": getattr(s, "fan", None),
                "env_alarm": getattr(s, "env_alarm", None), "last_env": getattr(s, "last_env", None)}

    def require(self, method: str) -> Callable[..., Any]:
        fn = getattr(self.sim, method, None)
        if not callable(fn):
            raise DomainError("SIM_NOT_SUPPORTED", f"El ESP32 virtual no implementa «{method}»", 501)
        return fn


_doors: dict[str, VirtualDoor] = {}
_doors_lock = threading.Lock()


def door(device_code: str) -> VirtualDoor:
    code = device_code.upper()
    with _doors_lock:
        if code not in _doors:
            with SessionLocal() as db:
                dev = db.execute(select(Device).where(Device.device_code == code)).scalar_one_or_none()
                if dev is None:
                    raise DomainError("DEVICE_NOT_FOUND", "Dispositivo no encontrado", 404)
                secret = decrypt_secret(dev.secret_encrypted)
                db.rollback()
            _doors[code] = VirtualDoor(code, secret)
        return _doors[code]


def all_doors() -> list[VirtualDoor]:
    with SessionLocal() as db:
        codes = list(db.execute(select(Device.device_code).order_by(Device.device_code)).scalars())
        db.rollback()
    return [door(c) for c in codes]


def reset() -> None:
    with _doors_lock:
        _doors.clear()


def call(vd: VirtualDoor, fn: Callable[[], Any], label: str) -> dict:
    """Run one virtual-device action, converting protocol failures into a panel message."""
    if not vd.online:
        raise DomainError("SIM_DEVICE_OFFLINE", "El ESP32 virtual está desconectado", 409)
    with vd.lock:
        try:
            result = fn()
        except esp32_sim.BadResponse as e:
            vd.last = {"action": label, "error": f"Respuesta rechazada por el ESP32 (fail-closed): {e}"}
            return vd.last
        except OSError as e:
            vd.last = {"action": label, "error": f"Sin conexión con el backend: {e}"}
            return vd.last
    if result is None:
        vd.last = {"action": label, "status": None, "data": None}
    else:
        vd.last = {"action": label, "status": result.status, "data": result.data}
    return vd.last


def heartbeat_tick() -> None:
    """Background: one heartbeat per online virtual door (runs every ``device_heartbeat_s``)."""
    for vd in all_doors():
        if vd.online:
            try:
                call(vd, vd.sim.heartbeat, "heartbeat")
            except DomainError:
                pass
