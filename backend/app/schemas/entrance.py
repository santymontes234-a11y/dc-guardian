"""Schemas for the main entrance (QR) and the server-room environment (DHT11)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import SaneDatetime


# ----------------------------------------------------------------- QR credentials (admin)
class QrIssueIn(BaseModel):
    """Permanent credential (no fields), or a temporary pass: ``valid_minutes`` (preferred: the
    server's clock decides) or an explicit ``expires_at``, optionally ``single_use``."""

    expires_at: SaneDatetime | None = None  # None = does not expire
    valid_minutes: int | None = Field(default=None, ge=5, le=60 * 24 * 30, description="Validez desde ahora")
    single_use: bool = Field(default=False, description="El primer acceso concedido consume el pase")

    @model_validator(mode="after")
    def _one_way_to_expire(self) -> "QrIssueIn":
        if self.expires_at is not None and self.valid_minutes is not None:
            raise ValueError("Usa expires_at o valid_minutes, no ambos")
        return self


class QrEngineer(BaseModel):
    id: int
    full_name: str
    position: str


class QrIssued(BaseModel):
    qr_text: str = Field(description="Texto completo del QR (`DCG-QR1:<token>`). Se muestra solo esta vez")
    prefix: str
    expires_at: datetime | None
    single_use: bool
    engineer: QrEngineer


class QrStatusOut(BaseModel):
    active: bool
    expired: bool = False  # still ACTIVA in the database but past its expiry: it will not open anything
    single_use: bool = False
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
