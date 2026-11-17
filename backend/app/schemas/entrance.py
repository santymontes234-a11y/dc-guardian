"""Schemas for the main entrance (QR) and the server-room environment (DHT11)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import SaneDatetime


# ----------------------------------------------------------------- QR credentials (admin)
class QrIssueIn(BaseModel):
    expires_at: SaneDatetime | None = None  # None = does not expire


class QrEngineer(BaseModel):
    id: int
    full_name: str
    position: str


class QrIssued(BaseModel):
    qr_text: str = Field(description="Texto completo del QR (`DCG-QR1:<token>`). Se muestra solo esta vez")
    prefix: str
    expires_at: datetime | None
    engineer: QrEngineer


class QrStatusOut(BaseModel):
    active: bool
    prefix: str | None
    created_at: datetime | None
    expires_at: datetime | None
    last_used_at: datetime | None


# ----------------------------------------------------------------- kiosk scan
class QrScanIn(BaseModel):
    qr_text: str = Field(min_length=1, max_length=512)


class QrScanOut(BaseModel):
    result: Literal["GRANTED", "DENIED"]
    reason_code: str | None = None
    reason: str | None = None
    display_name: str | None = None
    position: str | None = None
    area: str
    event_id: str


# ----------------------------------------------------------------- access log
class Zone(BaseModel):
    code: str | None
    name: str | None


class AccessLogRow(BaseModel):
    id: str
    source: Literal["access_session", "entrance_event"]
    at: datetime
    person: str | None
    engineer_id: str | None
    position: str | None
    zone: Zone
    method: Literal["QR", "RFID+ROSTRO", "BOTON_SALIDA"]
    direction: Literal["ENTRADA", "SALIDA"]
    result: Literal["GRANTED", "DENIED"]
    reason_code: str | None
    reason: str | None
    device_code: str | None


# ----------------------------------------------------------------- environment
class Thresholds(BaseModel):
    temp_high_c: float
    temp_critical_c: float
    humidity_low_pct: float
    humidity_high_pct: float
    fan_off_below_c: float


class EnvironmentLatest(BaseModel):
    device_code: str | None
    area: Zone | None
    temperature_c: float | None
    humidity_pct: float | None
    sensor: Literal["OK", "ERROR"] | None
    fan: bool | None
    alarm: bool | None
    conditions: list[str]
    at: datetime | None
    thresholds: Thresholds


class EnvironmentPoint(BaseModel):
    at: datetime
    temperature_c: float | None
    humidity_pct: float | None


class EnvironmentSeries(BaseModel):
    minutes: int
    items: list[EnvironmentPoint]
