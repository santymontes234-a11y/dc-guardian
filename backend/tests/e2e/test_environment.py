"""DHT11 in the server room (docs/contrato-qr-dht11.md §4): signed device endpoint, fan with
hysteresis, alarm, alerts without duplicates (re-armed when the condition clears), queries."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.db.types import utcnow
from app.main import app as fastapi_app
from app.models import Device, EnvironmentReading
from app.services import environment as env
from app.ws.hub import hub


def send(door, t, h=50.0, sensor="OK") -> dict:
    r = door.sim.call("POST", "/device/environment",
                      body={"temperature_c": t, "humidity_pct": h, "sensor": sensor})
    assert r.status == 200, r.data
    return r.data


def alert_count(f, type_: str) -> int:
    return sum(1 for a in f.ok("GET", "/api/v1/alerts", params={"limit": 200})["items"] if a["type"] == type_)


# ------------------------------------------------------------------ pure decision
@pytest.mark.parametrize("prev,t,h,expected", [
    (set(), 26.9, 50, (set(), False, False)),
    (set(), 27.0, 50, ({env.TEMP_HIGH}, True, False)),
    ({env.TEMP_HIGH}, 26.0, 50, ({env.TEMP_HIGH}, True, False)),  # hysteresis: off only below 26
    ({env.TEMP_HIGH}, 25.9, 50, (set(), False, False)),
    (set(), 32.0, 50, ({env.TEMP_HIGH, env.TEMP_CRITICAL}, True, True)),
    (set(), 22.0, 19.9, ({env.HUMIDITY}, False, True)),
    (set(), 22.0, 80.0, (set(), False, False)),  # range is inclusive
    (set(), 22.0, 80.1, ({env.HUMIDITY}, False, True)),
])
def test_evaluate(prev, t, h, expected):
    assert env.evaluate(prev, t, h, True) == expected


def test_evaluate_sensor_error_keeps_value_conditions_and_turns_fan_off():
    conds, fan, alarm = env.evaluate({env.TEMP_HIGH, env.HUMIDITY}, None, None, False)
    assert conds == {env.TEMP_HIGH, env.HUMIDITY, env.DHT_ERROR} and fan is False and alarm is False


# ------------------------------------------------------------------ device endpoint
def test_fan_hysteresis_and_alert_rearm(f, door):
    assert send(door, 26.9) == {"ok": True, "fan": False, "alarm": False}
    assert send(door, 27.0)["fan"] is True
    assert send(door, 26.5)["fan"] is True
    assert send(door, 26.0)["fan"] is True
    assert alert_count(f, "TEMPERATURA_ALTA") == 1  # persisting condition: no repeats
    assert send(door, 25.9)["fan"] is False
    assert send(door, 27.4)["fan"] is True
    assert alert_count(f, "TEMPERATURA_ALTA") == 2  # re-armed after it cleared


def test_critical_temperature_alarm_without_duplicates(f, door):
    out = send(door, 32.0)
    assert out == {"ok": True, "fan": True, "alarm": True}
    send(door, 33.5)
    send(door, 34.0)
    alerts = [a for a in f.ok("GET", "/api/v1/alerts")["items"] if a["type"] == "TEMPERATURA_CRITICA"]
    assert len(alerts) == 1 and alerts[0]["severity"] == "CRITICAL"
    msg = alerts[0]["message"]  # sensor, zone, date, value and action
    assert "DHT11" in msg and door.area["code"] in msg and "32.0 °C" in msg and "Acción" in msg and "UTC" in msg
    assert send(door, 31.0)["alarm"] is False
    send(door, 32.5)
    assert alert_count(f, "TEMPERATURA_CRITICA") == 2


def test_humidity_out_of_range(f, door):
    assert send(door, 22, 19.0) == {"ok": True, "fan": False, "alarm": True}
    send(door, 22, 15.0)
    assert send(door, 22, 50.0)["alarm"] is False
    assert send(door, 22, 85.0)["alarm"] is True
    alerts = [a for a in f.ok("GET", "/api/v1/alerts")["items"] if a["type"] == "HUMEDAD_FUERA_DE_RANGO"]
    assert len(alerts) == 2 and alerts[0]["severity"] == "WARN"


def test_sensor_error(f, door):
    send(door, 30.0)
    assert send(door, None, None, "ERROR") == {"ok": True, "fan": False, "alarm": False}
    send(door, None, None, "ERROR")
    assert alert_count(f, "SENSOR_DHT_ERROR") == 1
    # "OK" without values is treated as an error too (fail-safe).
    assert send(door, None, None, "OK")["fan"] is False
    assert alert_count(f, "SENSOR_DHT_ERROR") == 1
    # Recovery: temperature was high before the fault → no new TEMPERATURA_ALTA alert.
    assert send(door, 30.0)["fan"] is True
    assert alert_count(f, "TEMPERATURA_ALTA") == 1
    send(door, None, None, "ERROR")
    assert alert_count(f, "SENSOR_DHT_ERROR") == 2  # re-armed after recovery
    with SessionLocal() as db:
        last = db.query(EnvironmentReading).order_by(EnvironmentReading.id.desc()).first()
        assert last.sensor == "ERROR" and last.temperature_c is None and last.humidity_pct is None


def test_invalid_body_gets_a_signed_422(door):
    r = door.sim.call("POST", "/device/environment", body={"temperature_c": 20, "humidity_pct": 150, "sensor": "OK"})
    assert r.status == 422 and r.data["error"]["code"] == "VALIDATION_ERROR"
    r = door.sim.call("POST", "/device/environment", body={"temperature_c": 20, "humidity_pct": 50, "sensor": "MAL"})
    assert r.status == 422


def test_reading_is_stored_rounded_purged_and_pushed(f, door):
    with SessionLocal() as db:
        dev = db.query(Device).one()
        db.add(EnvironmentReading(device_id=dev.id, area_id=dev.area_id, temperature_c=20, humidity_pct=40,
                                  sensor="OK", created_at=utcnow() - timedelta(days=8)))
        db.commit()
    send(door, 23.456, 41.04)
    with SessionLocal() as db:
        rows = db.query(EnvironmentReading).all()
        assert len(rows) == 1  # the 8-day-old one was purged
        r = rows[0]
        assert (r.temperature_c, r.humidity_pct, r.area_id) == (23.5, 41.0, door.area["id"])
    evt = [e for e in hub.history if e["type"] == "environment"][-1]["data"]
    assert evt["temperature_c"] == 23.5 and evt["device_code"] == "DC-DOOR-01" and evt["fan"] is False
    assert evt["area"]["code"] == door.area["code"]


def test_unsigned_environment_is_rejected(door):
    status, _h, _b = door.sim.transport.request("POST", "/api/v1/device/environment",
                                                {"Content-Type": "application/json"}, b'{"temperature_c":40}')
    assert status == 401
    with SessionLocal() as db:
        assert db.query(EnvironmentReading).count() == 0


# ------------------------------------------------------------------ queries
def test_latest_and_series(f, door, auditor_api):
    empty = f.ok("GET", "/api/v1/monitoring/environment/latest")
    assert empty["temperature_c"] is None and empty["at"] is None
    assert empty["thresholds"] == {"temp_high_c": 27, "temp_critical_c": 32, "humidity_low_pct": 20,
                                   "humidity_high_pct": 80, "fan_off_below_c": 26}
    send(door, 24.0, 45.0)
    send(door, 28.0, 46.0)
    latest = auditor_api.get("/api/v1/monitoring/environment/latest").json()
    assert {k: latest[k] for k in ("device_code", "temperature_c", "humidity_pct", "sensor", "fan", "alarm")} == \
        {"device_code": "DC-DOOR-01", "temperature_c": 28.0, "humidity_pct": 46.0, "sensor": "OK",
         "fan": True, "alarm": False}
    assert latest["area"]["code"] == door.area["code"] and latest["conditions"] == ["TEMPERATURA_ALTA"]
    assert f.ok("GET", "/api/v1/monitoring/environment/latest",
                params={"device_code": "DC-DOOR-01"})["temperature_c"] == 28.0
    assert f.ok("GET", "/api/v1/monitoring/environment/latest",
                params={"device_code": "NOPE-9"})["temperature_c"] is None

    series = auditor_api.get("/api/v1/monitoring/environment", params={"minutes": 60}).json()
    assert series["minutes"] == 60
    assert [(p["temperature_c"], p["humidity_pct"]) for p in series["items"]] == [(24.0, 45.0), (28.0, 46.0)]
    assert f.c.get("/api/v1/monitoring/environment", params={"minutes": 0}).status_code == 422
    with TestClient(fastapi_app) as anon:
        assert anon.get("/api/v1/monitoring/environment/latest").status_code == 401


def test_series_is_downsampled_to_1440_points(f, door):
    now = utcnow()
    with SessionLocal() as db:
        dev = db.query(Device).one()
        db.add_all([EnvironmentReading(device_id=dev.id, area_id=dev.area_id, temperature_c=20 + i % 5,
                                       humidity_pct=50, sensor="OK", created_at=now - timedelta(seconds=10 * i))
                    for i in range(3000)])
        db.commit()
    items = f.ok("GET", "/api/v1/monitoring/environment", params={"minutes": 1440})["items"]
    assert 0 < len(items) <= 1440
    assert items[0]["at"] < items[-1]["at"]
