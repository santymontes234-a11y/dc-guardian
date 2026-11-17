"""Server-room environment (DHT11 on the door ESP32, contract §4).

Per reading:
- Stored in ``environment_readings`` (device, area, values, sensor state, UTC time); readings
  older than ``DCG_ENVIRONMENT_RETENTION_DAYS`` (7) are purged.
- ``fan`` on at ``t >= temp_high_c``; it stays on until ``t < temp_high_c - 1`` (hysteresis).
- ``alarm`` at ``t >= temp_critical_c`` or humidity outside ``[humidity_low, humidity_high]``.
- Alerts are raised when a condition *appears* and are re-armed when it disappears, so a
  persisting condition never repeats its alert. Conditions active after each reading are
  stored with it. While the sensor is in ERROR the temperature/humidity conditions keep their
  previous value (unknown is not "resolved") and the fan is off, as on the firmware.
- Every reading is pushed by WebSocket as ``environment``.
"""

from __future__ import annotations

import math
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Area, Device, EnvironmentReading
from app.models.enums import SensorReading
from app.services import alerts
from app.services.context import ActorCtx
from app.ws.hub import defer

TEMP_HIGH = "TEMPERATURA_ALTA"
TEMP_CRITICAL = "TEMPERATURA_CRITICA"
HUMIDITY = "HUMEDAD_FUERA_DE_RANGO"
DHT_ERROR = "SENSOR_DHT_ERROR"
CONDITIONS = (TEMP_HIGH, TEMP_CRITICAL, HUMIDITY, DHT_ERROR)
_VALUE_CONDITIONS = frozenset({TEMP_HIGH, TEMP_CRITICAL, HUMIDITY})
HYSTERESIS_C = 1.0
MAX_POINTS = 1440


def thresholds() -> dict:
    s = get_settings()
    return {"temp_high_c": s.temp_high_c, "temp_critical_c": s.temp_critical_c,
            "humidity_low_pct": s.humidity_low_pct, "humidity_high_pct": s.humidity_high_pct,
            "fan_off_below_c": s.temp_high_c - HYSTERESIS_C}


def _conds(text: str | None) -> set[str]:
    return {c for c in (text or "").split(",") if c in CONDITIONS}


def _r1(v: float | None) -> float | None:
    return None if v is None or not math.isfinite(v) else round(float(v), 1)


def evaluate(prev: set[str], temperature_c: float | None, humidity_pct: float | None, sensor_ok: bool
             ) -> tuple[set[str], bool, bool]:
    """Pure decision: (conditions, fan, alarm) for a reading given the previous conditions."""
    s = get_settings()
    if not sensor_ok or temperature_c is None or humidity_pct is None:
        return (prev & _VALUE_CONDITIONS) | {DHT_ERROR}, False, False
    conds: set[str] = set()
    if temperature_c >= s.temp_high_c or (TEMP_HIGH in prev and temperature_c >= s.temp_high_c - HYSTERESIS_C):
        conds.add(TEMP_HIGH)
    if temperature_c >= s.temp_critical_c:
        conds.add(TEMP_CRITICAL)
    if humidity_pct < s.humidity_low_pct or humidity_pct > s.humidity_high_pct:
        conds.add(HUMIDITY)
    fan = TEMP_HIGH in conds
    alarm = TEMP_CRITICAL in conds or HUMIDITY in conds
    return conds, fan, alarm


def _last(db: Session, device_id: int) -> EnvironmentReading | None:
    return db.execute(
        select(EnvironmentReading).where(EnvironmentReading.device_id == device_id)
        .order_by(EnvironmentReading.created_at.desc(), EnvironmentReading.id.desc()).limit(1)
    ).scalar_one_or_none()


def _alert_message(cond: str, dev: Device, area: Area | None, r: EnvironmentReading) -> str:
    s = get_settings()
    zone = f"{area.name} ({area.code})" if area else "zona desconocida"
    at = r.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
    head = f"Sensor DHT11 de {dev.device_code} · zona {zone} · {at}: "
    if cond == TEMP_HIGH:
        return head + (f"temperatura {r.temperature_c:.1f} °C ≥ {s.temp_high_c:g} °C. "
                       f"Acción: ventilador encendido hasta bajar de {s.temp_high_c - HYSTERESIS_C:g} °C")
    if cond == TEMP_CRITICAL:
        return head + (f"temperatura CRÍTICA {r.temperature_c:.1f} °C ≥ {s.temp_critical_c:g} °C. "
                       "Acción: alarma sonora y ventilador encendido")
    if cond == HUMIDITY:
        return head + (f"humedad {r.humidity_pct:.1f} % fuera de rango "
                       f"[{s.humidity_low_pct:g}, {s.humidity_high_pct:g}] %. Acción: alarma sonora")
    return head + "el sensor no responde (3 lecturas fallidas). Acción: ventilador apagado, revisar el sensor"


def reading_dict(r: EnvironmentReading, dev: Device | None, area: Area | None) -> dict:
    return {
        "device_code": dev.device_code if dev else None,
        "area": {"code": area.code, "name": area.name} if area else None,
        "temperature_c": r.temperature_c, "humidity_pct": r.humidity_pct, "sensor": str(r.sensor),
        "fan": r.fan, "alarm": r.alarm, "conditions": sorted(_conds(r.conditions)),
        "at": r.created_at.isoformat(),
    }


def record(db: Session, ctx: ActorCtx, dev: Device, temperature_c: float | None, humidity_pct: float | None,
           sensor: str) -> dict:
    """Store one reading and return the device reply ``{ok, fan, alarm}``. Caller commits."""
    s = get_settings()
    t, h = _r1(temperature_c), _r1(humidity_pct)
    sensor_ok = sensor == SensorReading.OK and t is not None and h is not None
    prev = _last(db, dev.id)
    prev_conds = _conds(prev.conditions) if prev else set()
    conds, fan, alarm = evaluate(prev_conds, t, h, sensor_ok)
    r = EnvironmentReading(
        device_id=dev.id, area_id=dev.area_id, temperature_c=t if sensor_ok else None,
        humidity_pct=h if sensor_ok else None, sensor=SensorReading.OK if sensor_ok else SensorReading.ERROR,
        fan=fan, alarm=alarm, conditions=",".join(c for c in CONDITIONS if c in conds), created_at=ctx.now,
    )
    db.add(r)
    db.flush()
    area = db.get(Area, dev.area_id) if dev.area_id else None
    for cond in CONDITIONS:
        if cond in conds and cond not in prev_conds:
            alerts.raise_alert(db, ctx, cond, _alert_message(cond, dev, area, r), device_id=dev.id)
            ctx.audit(db, "environment.condition_raised", "device", dev.id,
                      {"condition": cond, "temperature_c": r.temperature_c, "humidity_pct": r.humidity_pct,
                       "fan": fan, "alarm": alarm})
        elif cond in prev_conds and cond not in conds:
            ctx.audit(db, "environment.condition_cleared", "device", dev.id,
                      {"condition": cond, "temperature_c": r.temperature_c, "humidity_pct": r.humidity_pct})
    cutoff = ctx.now - timedelta(days=s.environment_retention_days)
    db.execute(delete(EnvironmentReading).where(EnvironmentReading.created_at < cutoff))
    defer(db, "environment", reading_dict(r, dev, area))
    return {"ok": True, "fan": fan, "alarm": alarm}


# ------------------------------------------------------------------ queries
def _device_id(db: Session, device_code: str | None) -> int | None:
    if not device_code:
        return None
    return db.execute(select(Device.id).where(Device.device_code == device_code.upper())).scalar_one_or_none()


def latest(db: Session, device_code: str | None = None) -> dict:
    stmt = select(EnvironmentReading)
    if device_code:
        stmt = stmt.where(EnvironmentReading.device_id == (_device_id(db, device_code) or -1))
    r = db.execute(stmt.order_by(EnvironmentReading.created_at.desc(), EnvironmentReading.id.desc()).limit(1)
                   ).scalar_one_or_none()
    if r is None:
        return {"device_code": device_code.upper() if device_code else None, "area": None, "temperature_c": None,
                "humidity_pct": None, "sensor": None, "fan": None, "alarm": None, "conditions": [], "at": None,
                "thresholds": thresholds()}
    dev = db.get(Device, r.device_id)
    area = db.get(Area, r.area_id) if r.area_id else None
    return {**reading_dict(r, dev, area), "thresholds": thresholds()}


def series(db: Session, now, minutes: int, device_code: str | None = None) -> dict:
    """Readings of the last ``minutes``, oldest first, down-sampled to at most 1440 points."""
    stmt = select(EnvironmentReading.created_at, EnvironmentReading.temperature_c, EnvironmentReading.humidity_pct
                  ).where(EnvironmentReading.created_at >= now - timedelta(minutes=minutes))
    if device_code:
        stmt = stmt.where(EnvironmentReading.device_id == (_device_id(db, device_code) or -1))
    rows = db.execute(stmt.order_by(EnvironmentReading.created_at, EnvironmentReading.id)).all()
    if len(rows) > MAX_POINTS:
        step = math.ceil(len(rows) / MAX_POINTS)
        rows = rows[::step]
    return {"minutes": minutes, "items": [{"at": at.isoformat(), "temperature_c": t, "humidity_pct": h}
                                          for at, t, h in rows]}
