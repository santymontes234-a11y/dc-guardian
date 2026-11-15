"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import uuid

from fastapi import FastAPI, Request

from app.api.v1.router import api_router
from app.core.config import PROJECT_ROOT, get_settings
from app.core.errors import install_error_handlers
from app.core.logging import setup_logging
from app.services.scheduler import scheduler_lifespan
from app.ws.hub import hub
from app.ws.router import router as ws_router

log = logging.getLogger(__name__)


def _warm_up_face_model() -> None:
    try:
        from app.vision import get_provider

        provider = get_provider()
        if hasattr(provider, "warm_up"):
            provider.warm_up()
        log.info("Face provider ready: %s", provider.name)
    except Exception:  # verification will fail closed and retry the load on demand
        log.exception("Face model warm-up failed")

_CID_RE = re.compile(r"^[A-Za-z0-9-]{8,32}$")


def create_app() -> FastAPI:
    setup_logging()
    settings = get_settings()

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        hub.bind(asyncio.get_running_loop())
        if settings.env != "test":  # load the face model once, off the event loop
            asyncio.get_running_loop().run_in_executor(None, _warm_up_face_model)
        async with scheduler_lifespan():
            yield

    app = FastAPI(
        lifespan=lifespan,
        title="DC Guardian API",
        version="0.8.0",
        description="Control de acceso inteligente para Data Center (proyecto académico).",
        docs_url=None if settings.env == "prod" else "/docs",
        redoc_url=None,
    )

    @app.middleware("http")
    async def correlation_and_headers(request: Request, call_next):
        incoming = request.headers.get("x-correlation-id", "")
        request.state.correlation_id = incoming if _CID_RE.match(incoming) else uuid.uuid4().hex
        response = await call_next(request)
        response.headers["X-Correlation-Id"] = request.state.correlation_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    install_error_handlers(app)
    app.include_router(api_router)
    app.include_router(ws_router)

    frontend_dir = PROJECT_ROOT / "frontend"
    if (frontend_dir / "index.html").exists():  
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

    return app


app = create_app()
