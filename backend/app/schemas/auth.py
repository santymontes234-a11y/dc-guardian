from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AdminRole


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)


class AdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    full_name: str
    role: AdminRole
    engineer_id: int | None = None
    last_login_at: datetime | None


class LoginOut(BaseModel):
    admin: AdminOut
    expires_at: datetime
