from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.models import normalize_uid
from app.models.enums import CardStatus, DeviceStatus, EngineerStatus
from app.schemas.common import DbId, Text

Code = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{1,29}$")]
# (the pattern runs before to_upper, hence the mixed-case classes)


# ----------------------------------------------------------------- cards
class CardCreate(BaseModel):
    uid: str
    label: Text(1, 60) | None = None
    engineer_id: DbId | None = None

    @field_validator("uid")
    @classmethod
    def _uid(cls, v: str) -> str:
        return normalize_uid(v)


class CardUpdate(BaseModel):
    label: Text(1, 60) | None = None


class CardAssign(BaseModel):
    engineer_id: DbId | None  # None = unassign


class CardStatusChange(BaseModel):
    status: CardStatus
    reason: Text(3, 300)


class EngineerMini(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    engineer_id: str
    full_name: str
    status: EngineerStatus


class CardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uid: str
    label: str | None
    status: CardStatus
    engineer: EngineerMini | None
    assigned_at: datetime | None
    failed_attempts: int
    locked_until: datetime | None
    created_at: datetime


# ----------------------------------------------------------------- areas
class AreaCreate(BaseModel):
    code: Code
    name: Text(2, 80)
    security_level: int = Field(default=3, ge=1, le=5)
    description: Text(0, 500) | None = None


class AreaUpdate(BaseModel):
    name: Text(2, 80) | None = None
    security_level: int | None = Field(default=None, ge=1, le=5)
    description: Text(0, 500) | None = None


class AreaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    security_level: int
    description: str | None


# ----------------------------------------------------------------- devices
class DeviceCreate(BaseModel):
    device_code: Code
    name: Text(2, 80)
    area_id: DbId
    presence_threshold_cm: int = Field(default=50, ge=2, le=400)
    door_open_ms: int = Field(default=5000, ge=1000, le=30000)


class DeviceUpdate(BaseModel):
    name: Text(2, 80) | None = None
    area_id: DbId | None = None
    presence_threshold_cm: int | None = Field(default=None, ge=2, le=400)
    door_open_ms: int | None = Field(default=None, ge=1000, le=30000)
    enabled: bool | None = None


class DeviceOut(BaseModel):
    """Never includes the secret."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    device_code: str
    name: str
    area: AreaOut
    presence_threshold_cm: int
    door_open_ms: int
    status: DeviceStatus
    firmware_version: str | None
    last_seen_at: datetime | None
    created_at: datetime


class DeviceWithSecret(BaseModel):
    device: DeviceOut
    secret: str = Field(description="Secreto HMAC. Se muestra UNA sola vez; cópialo al firmware.")
