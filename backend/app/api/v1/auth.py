from fastapi import APIRouter, Request, Response

from app.api.deps import CurrentAdmin, DbSession
from app.core.config import get_settings
from app.core.errors import DomainError
from app.core.ratelimit import SlidingWindowLimiter
from app.schemas.auth import AdminOut, LoginIn, LoginOut
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])

login_limiter = SlidingWindowLimiter(get_settings().login_rate_per_minute, 60)


@router.post("/login", response_model=LoginOut)
def login(body: LoginIn, request: Request, response: Response, db: DbSession):
    client_ip = request.client.host if request.client else "unknown"
    if not login_limiter.hit(client_ip):
        raise DomainError("RATE_LIMITED", "Demasiados intentos; espera un minuto", 429, {"Retry-After": "60"})

    result = auth_service.login(db, body.username, body.password, request.state.correlation_id)
    s = get_settings()
    response.set_cookie(
        s.cookie_name,
        result.token,
        max_age=s.jwt_expire_minutes * 60,
        httponly=True,
        secure=s.cookie_secure,
        samesite="strict",
        path="/",
    )
    return LoginOut(admin=AdminOut.model_validate(result.admin), expires_at=result.expires_at)


@router.post("/logout", status_code=204)
def logout(admin: CurrentAdmin, request: Request, db: DbSession):
    auth_service.logout(db, admin, request.state.correlation_id)
    response = Response(status_code=204)
    response.delete_cookie(get_settings().cookie_name, path="/")
    return response


@router.get("/me", response_model=AdminOut)
def me(admin: CurrentAdmin):
    return admin
