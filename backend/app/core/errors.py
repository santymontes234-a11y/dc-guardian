"""Domain errors and the uniform JSON error envelope."""

from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)


class DomainError(Exception):
    """Expected business error, rendered as ``{"error": {code, message, correlation_id}}``."""

    def __init__(self, code: str, message: str, status: int = 400, headers: dict | None = None,
                 details: list | dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.headers = headers
        self.details = details  # optional machine-readable context (never secrets/biometrics)


def not_found(code: str, message: str) -> DomainError:
    return DomainError(code, message, 404)


def _correlation_id(request: Request) -> str:
    return getattr(request.state, "correlation_id", None) or uuid.uuid4().hex


def _envelope(request: Request, status: int, code: str, message: str, headers=None, **extra) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "correlation_id": _correlation_id(request), **extra}}
    return JSONResponse(status_code=status, content=body, headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain(request: Request, exc: DomainError):
        extra = {"details": exc.details} if exc.details is not None else {}
        return _envelope(request, exc.status, exc.code, exc.message, exc.headers, **extra)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        code = {401: "UNAUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(
            exc.status_code, "HTTP_ERROR"
        )
        return _envelope(request, exc.status_code, code, str(exc.detail), getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        details = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        return _envelope(request, 422, "VALIDATION_ERROR", "Datos de entrada inválidos", details=details)

    @app.exception_handler(IntegrityError)
    async def _integrity(request: Request, exc: IntegrityError):
        # Services pre-check uniqueness; this is the race-condition safety net.
        log.warning("Integrity error (correlation_id=%s): %s", _correlation_id(request), exc.orig)
        return _envelope(request, 409, "CONFLICT", "El registro entra en conflicto con datos existentes")

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.exception("Unhandled error (correlation_id=%s)", _correlation_id(request))
        return _envelope(request, 500, "INTERNAL_ERROR", "Error interno del servidor")
