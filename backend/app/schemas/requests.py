from datetime import datetime, timedelta
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.models.card import normalize_uid
from app.models.enums import RequestStatus
from app.schemas.common import DbId, SaneDatetime, Text
from app.schemas.engineers import EngineerCode

MAX_DURATION_MINUTES = 1440


def _uid(value: str) -> str:
    return normalize_uid(value)  # ValueError → 422


CardUid = Annotated[Text(1, 40), AfterValidator(_uid)]


class RequestCreate(BaseModel):
    """New authorization request (Registro 2).

    ``engineer_id`` accepts the public *ID de ingeniero* (``"ENG-0001"``) or the internal numeric
    id. The card is given by its RFID UID (``card_uid``) or its internal ``card_id``. The window is ``start_at`` plus either
    ``duration_minutes`` or ``end_at`` (if both are sent they must agree).
    """

    engineer_id: DbId | EngineerCode
    card_id: DbId | None = None
    card_uid: CardUid | None = None
    area_id: DbId
    reason: Text(5, 1000)
    start_at: SaneDatetime  # must include a timezone offset
    end_at: SaneDatetime | None = None
    duration_minutes: int | None = Field(default=None, ge=1, le=MAX_DURATION_MINUTES)
    observations: Text(1, 1000) | None = None

    @model_validator(mode="after")
    def _check(self) -> "RequestCreate":
        if (self.card_id is None) == (self.card_uid is None):
            raise ValueError("Indica la tarjeta por card_id o por card_uid (uno de los dos)")
        if self.end_at is not None:
            if self.end_at <= self.start_at:
                raise ValueError("La hora de finalización debe ser posterior a la de inicio")
            span = self.end_at - self.start_at
            if span % timedelta(minutes=1):
                raise ValueError("La ventana debe ser un número entero de minutos")
            minutes = int(span / timedelta(minutes=1))
            if minutes > MAX_DURATION_MINUTES:
                raise ValueError(f"La duración máxima es de {MAX_DURATION_MINUTES} minutos (24 h)")
            if self.duration_minutes is not None and self.duration_minutes != minutes:
                raise ValueError("La duración no coincide con las horas de inicio y finalización")
            self.duration_minutes = minutes
        if self.duration_minutes is None:
            raise ValueError("Indica la duración o la hora de finalización")
        return self


class ReviewIn(BaseModel):
    notes: Text(3, 500) | None = None


class ReviewRequiredIn(BaseModel):
    notes: Text(3, 500)


class _Ref(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int


class EngineerRef(_Ref):
    engineer_id: str  # public "ID de ingeniero"
    full_name: str
    department: str
    status: str


class CardRef(_Ref):
    uid: str
    status: str


class AreaRef(_Ref):
    code: str
    name: str


class AdminRef(_Ref):
    username: str
    full_name: str


class RequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    engineer: EngineerRef
    card: CardRef
    area: AreaRef
    reason: str
    observations: str | None
    start_at: datetime
    duration_minutes: int
    end_at: datetime
    status: RequestStatus
    in_force: bool
    creator: AdminRef | None
    reviewer: AdminRef | None
    reviewed_at: datetime | None
    review_notes: str | None
    closer: AdminRef | None
    closed_at: datetime | None
    close_notes: str | None
    first_used_at: datetime | None
    use_count: int
    created_at: datetime


class RequestStats(BaseModel):
    """Counts per status plus how many approved requests are in force right now."""

    by_status: dict[RequestStatus, int]
    in_force: int
    total: int
