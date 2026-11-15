"""Periodic background jobs (single-process asyncio loops).

- Requests sweep (``scheduler_interval_s``, 60 s): EXPIRADA / FINALIZADA.
- Access sweep (``device_sweep_interval_s``, 10 s): session timeouts, unused grants, devices
  without heartbeat → OFFLINE + ``DEVICE_OFFLINE`` alert, purge of old nonces.
- Simulation only: heartbeats of the virtual ESP32 doors (``device_heartbeat_s``).
The access engine never relies on these loops for its decisions; they keep the state tidy.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import delete

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.db.types import utcnow
from app.models import DeviceNonce
from app.services import access_engine
from app.services import requests as requests_service

log = logging.getLogger(__name__)


def run_once() -> dict[str, int]:
    with SessionLocal() as db:
        counts = requests_service.sweep(db)
    if any(counts.values()):
        log.info("Request sweep: %s", counts)
    return counts


def run_access_sweep(now=None) -> dict[str, int]:
    now = now or utcnow()
    with SessionLocal() as db:
        counts = access_engine.sweep(db, now)
        keep = timedelta(seconds=2 * get_settings().device_clock_skew_s + 60)
        purged = db.execute(delete(DeviceNonce).where(DeviceNonce.seen_at < now - keep)).rowcount
        db.commit()
    counts["nonces_purged"] = purged or 0
    if counts["timeouts"] or counts["offline"]:
        log.info("Access sweep: %s", counts)
    return counts


async def _loop(fn: Callable[[], object], interval_s: int, name: str) -> None:
    while True:
        try:
            await asyncio.to_thread(fn)
        except Exception:  # keep the loop alive
            log.exception("Scheduler job %s failed", name)
        await asyncio.sleep(interval_s)


@contextlib.asynccontextmanager
async def scheduler_lifespan():
    s = get_settings()
    tasks: list[asyncio.Task] = []
    if s.scheduler_enabled:
        tasks.append(asyncio.create_task(_loop(run_once, s.scheduler_interval_s, "requests")))
        tasks.append(asyncio.create_task(_loop(run_access_sweep, s.device_sweep_interval_s, "access")))
        if s.simulation:
            from app.sim import service as sim

            async def _sim_heartbeats():
                await asyncio.sleep(2)  # let uvicorn start accepting connections
                await _loop(sim.heartbeat_tick, s.device_heartbeat_s, "sim-heartbeat")

            tasks.append(asyncio.create_task(_sim_heartbeats()))
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
