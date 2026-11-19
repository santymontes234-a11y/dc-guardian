"""In-process real-time event hub for ``/ws/events``.

Services run in worker threads; they never publish directly. They *defer* events on the DB
session (``defer(db, type, data)``) and the hub publishes them only **after the transaction
commits** (SQLAlchemy ``after_commit``), so a client never sees an event for data that was
rolled back. Delivery is best-effort: a slow client loses events instead of blocking writers.

Event envelope: ``{"type": "access.granted", "ts": "...", "data": {...}}``.
Types: ``access.*`` (session changes), ``alert.created``, ``alert.acknowledged``,
``device.status``, ``device.presence``, ``request.updated``, ``entrance.scan`` (QR scan at the
main entrance, access-log row) and ``environment`` (DHT11 reading).
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Callable

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.db.types import utcnow

log = logging.getLogger(__name__)

_QUEUE_MAX = 200
_PENDING_KEY = "dcg_pending_events"


class EventHub:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._clients: set[asyncio.Queue] = set()
        self._lock = threading.Lock()
        self._listeners: list[Callable[[str, dict[str, Any]], None]] = []
        self.history: list[dict] = []  # last events, for tests and late-joining dashboards

    def add_listener(self, fn: Callable[[str, dict[str, Any]], None]) -> None:
        """Server-side subscriber (e.g. Telegram). It runs in the publishing thread after the
        commit, so it must return quickly and never raise (exceptions are logged and ignored)."""
        with self._lock:
            if fn not in self._listeners:
                self._listeners.append(fn)

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAX)
        with self._lock:
            self._clients.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._clients.discard(q)

    def _fanout(self, evt: dict) -> None:
        with self._lock:
            clients = list(self._clients)
        for q in clients:
            try:
                q.put_nowait(evt)
            except asyncio.QueueFull:  # slow consumer: drop rather than block
                pass

    def publish(self, type_: str, data: dict[str, Any]) -> None:
        evt = {"type": type_, "ts": utcnow().isoformat(), "data": data}
        with self._lock:
            self.history.append(evt)
            del self.history[:-100]
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                fn(type_, data)
            except Exception:  # noqa: BLE001 — a listener must never break the commit or the UI
                log.exception("Event listener failed")
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(self._fanout, evt)
        except RuntimeError:  # loop shutting down
            pass


hub = EventHub()


def defer(db: Session, type_: str, data: dict[str, Any]) -> None:
    """Queue an event to be published when ``db`` commits (dropped on rollback)."""
    db.info.setdefault(_PENDING_KEY, []).append((type_, data))


@event.listens_for(Session, "after_commit")
def _publish_after_commit(session: Session) -> None:
    for type_, data in session.info.pop(_PENDING_KEY, []):
        try:
            hub.publish(type_, data)
        except Exception:  # noqa: BLE001 — never break a commit because of the UI
            log.exception("Event publish failed")


@event.listens_for(Session, "after_rollback")
def _drop_after_rollback(session: Session) -> None:
    session.info.pop(_PENDING_KEY, None)
