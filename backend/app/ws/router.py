"""``/ws/events``: real-time events for the dashboard (admin/auditor cookie) and the kiosk (token).

Authentication:
- Admin/auditor: session cookie at the handshake. The ``Origin`` must match the ``Host``
  (cross-site WebSocket hijacking). The session is re-validated every ``REVALIDATE_S`` and the
  socket is closed (4401) after logout, expiry or deactivation.
- Kiosk: the token goes in the **first message** ``{"kiosk_token": "..."}``, never in the URL
  (URLs end up in access logs and browser history).

The kiosk only receives ``access.*`` events, projected to what it displays (no card UID, no
request or score data): it is an unattended screen next to the door.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
from urllib.parse import urlsplit

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.errors import DomainError
from app.db.session import ReadSessionLocal
from app.services.auth import admin_from_token
from app.ws.hub import hub

log = logging.getLogger(__name__)
router = APIRouter()

REVALIDATE_S = 60
KIOSK_AUTH_TIMEOUT_S = 5
_KIOSK_FIELDS = ("id", "device_code", "direction", "state", "reason_code", "reason")


def _admin_role(token: str) -> str | None:
    with ReadSessionLocal() as db:
        try:
            return str(admin_from_token(db, token).role)
        except DomainError:
            return None


def _kiosk_token_ok(value: object) -> bool:
    from app.api.v1.kiosk import kiosk_token

    return isinstance(value, str) and hmac.compare_digest(value.encode(), kiosk_token().encode())


def kiosk_view(evt: dict) -> dict:
    data = evt.get("data") or {}
    eng = data.get("engineer") or {}
    return {**evt, "data": {**{k: data.get(k) for k in _KIOSK_FIELDS},
                            "engineer": {"full_name": eng.get("full_name")} if eng else None}}


async def _cookie_role(ws: WebSocket) -> tuple[str | None, str | None]:
    cookie = ws.cookies.get(get_settings().cookie_name)
    if not cookie:
        return None, None
    origin = ws.headers.get("origin")
    if origin and urlsplit(origin).netloc != ws.headers.get("host"):
        log.warning("WebSocket rejected: origin %s does not match host", origin)
        return None, None
    return await run_in_threadpool(_admin_role, cookie), cookie


@router.websocket("/ws/events")
async def events(ws: WebSocket):
    role, cookie = await _cookie_role(ws)
    await ws.accept()
    if role is None:  # no valid admin cookie: the only other option is a kiosk token message
        try:
            msg = json.loads(await asyncio.wait_for(ws.receive_text(), KIOSK_AUTH_TIMEOUT_S))
        except (asyncio.TimeoutError, ValueError, WebSocketDisconnect, RuntimeError):
            msg = None
        if not (isinstance(msg, dict) and _kiosk_token_ok(msg.get("kiosk_token"))):
            await ws.close(code=4401)
            return
        role = "kiosk"

    queue = hub.subscribe()
    await ws.send_json({"type": "hello", "data": {"role": role}})

    async def pump():
        while True:
            evt = await queue.get()
            if role == "kiosk":
                if not evt["type"].startswith("access."):
                    continue
                evt = kiosk_view(evt)
            await ws.send_json(evt)

    async def drain():  # detect client disconnects; incoming messages are ignored
        while True:
            await ws.receive_text()

    async def revalidate():  # logout / expiry / deactivation closes the socket
        while True:
            await asyncio.sleep(REVALIDATE_S)
            if await run_in_threadpool(_admin_role, cookie) is None:
                await ws.close(code=4401)
                return

    tasks = [asyncio.create_task(pump()), asyncio.create_task(drain())]
    if role != "kiosk":
        tasks.append(asyncio.create_task(revalidate()))
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    finally:
        for t in tasks:
            t.cancel()
        hub.unsubscribe(queue)
