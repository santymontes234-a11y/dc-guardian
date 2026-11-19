"""Telegram notifications for alerts (a push to the administrator's phone).

Every alert created by ``alerts.raise_alert`` is published on the event hub **after the
transaction commits** (``alert.created``). This module listens to the hub and, when Telegram is
configured and the alert is at least ``DCG_TELEGRAM_MIN_SEVERITY``, queues one message.

Design rules (the notification channel must never hurt the access control):
- Sending never runs inside a request or a database transaction: a single daemon thread drains
  a small bounded queue. If Telegram is slow or down, alerts still work and messages are dropped.
- Plain-text messages (no ``parse_mode``): alert text can never inject formatting or links.
- A per-minute cap (``DCG_TELEGRAM_RATE_PER_MINUTE``) stops a flood of alerts from flooding the chat.
- The bot token is a secret: it lives only in ``backend/.env``, goes only into the request URL and
  is never logged, audited or returned by the API (errors are rewritten without the URL).

This module deliberately imports no database code so it can be tested in isolation.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

from app.core.config import get_settings
from app.core.ratelimit import SlidingWindowLimiter

log = logging.getLogger(__name__)

API_URL = "https://api.telegram.org/bot{token}/sendMessage"
MAX_TEXT = 1000  # Telegram allows 4096; an alert never needs more
_QUEUE_MAX = 50
_SEV_RANK = {"INFO": 0, "WARN": 1, "CRITICAL": 2}
_SEV_LABEL = {"INFO": "ℹ️ INFO", "WARN": "⚠️ AVISO", "CRITICAL": "🚨 CRÍTICA"}


class NotifyError(Exception):
    """A message could not be sent. The text is safe to show (it never contains the token)."""


_queue: queue.Queue[str] = queue.Queue(maxsize=_QUEUE_MAX)
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()
_limiter: SlidingWindowLimiter | None = None
_installed = False


# ------------------------------------------------------------------ configuration
def is_enabled() -> bool:
    s = get_settings()
    return bool(s.telegram_bot_token and s.telegram_chat_id)


def _rate_limiter() -> SlidingWindowLimiter:
    global _limiter
    per_min = get_settings().telegram_rate_per_minute
    if _limiter is None or _limiter.max_events != per_min:
        _limiter = SlidingWindowLimiter(max_events=per_min, window_s=60)
    return _limiter


# ------------------------------------------------------------------ message
def _when(iso: Any) -> str:
    try:
        return datetime.fromisoformat(str(iso)).strftime("%Y-%m-%d %H:%M:%S UTC")
    except ValueError:
        return str(iso or "")


def format_alert(alert: dict[str, Any], site: str | None = None) -> str:
    """Plain-text message for one alert dict (the ``alerts.to_dict`` shape)."""
    site = site or get_settings().site_name
    sev = str(alert.get("severity") or "WARN")
    lines = [f"{_SEV_LABEL.get(sev, sev)} · {site}", f"Alerta: {alert.get('type', '?')}"]
    if alert.get("message"):
        lines.append(str(alert["message"]))
    if alert.get("created_at"):
        lines.append(_when(alert["created_at"]))
    return "\n".join(lines)[:MAX_TEXT]


# ------------------------------------------------------------------ transport
def _post(token: str, chat_id: str, text: str, timeout: float) -> None:
    """One ``sendMessage`` call. Raises ``NotifyError`` with a token-free message."""
    body = json.dumps({"chat_id": chat_id, "text": text, "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(
        API_URL.format(token=token), data=body, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "dc-guardian"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — fixed https host
            payload = json.loads(resp.read(65536) or b"{}")
    except urllib.error.HTTPError as exc:
        hint = {401: "token inválido", 400: "chat id incorrecto o el bot no puede escribir ahí",
                403: "el bot fue bloqueado o expulsado del chat", 404: "token inválido",
                429: "demasiados mensajes, Telegram pidió esperar"}.get(exc.code, "error del servicio")
        raise NotifyError(f"Telegram respondió HTTP {exc.code} ({hint})") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise NotifyError("No se pudo conectar con Telegram (red o tiempo de espera)") from None
    except ValueError:
        raise NotifyError("Respuesta de Telegram no válida") from None
    if not (isinstance(payload, dict) and payload.get("ok") is True):
        raise NotifyError("Telegram no aceptó el mensaje")


def send_text(text: str) -> None:
    """Send now, in the caller's thread (used by the admin 'test' endpoint)."""
    s = get_settings()
    if not (s.telegram_bot_token and s.telegram_chat_id):
        raise NotifyError("Telegram no está configurado (DCG_TELEGRAM_BOT_TOKEN y DCG_TELEGRAM_CHAT_ID)")
    _post(s.telegram_bot_token, s.telegram_chat_id, text[:MAX_TEXT], s.telegram_timeout_s)


# ------------------------------------------------------------------ background delivery
def _run_worker() -> None:
    while True:
        text = _queue.get()
        try:
            send_text(text)
        except NotifyError as exc:
            log.warning("Telegram: %s", exc)
        except Exception:  # noqa: BLE001 — the worker must survive anything
            log.exception("Telegram: unexpected error while sending")
        finally:
            _queue.task_done()


def _enqueue(text: str) -> None:
    global _worker
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run_worker, name="telegram-notifier", daemon=True)
            _worker.start()
    try:
        _queue.put_nowait(text)
    except queue.Full:
        log.warning("Telegram: queue full, message dropped")


def flush(timeout: float = 5.0) -> bool:
    """Wait until queued messages were handled (tests, shutdown). False on timeout."""
    deadline = time.monotonic() + timeout
    while _queue.unfinished_tasks:
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)
    return True


# ------------------------------------------------------------------ hub listener
def should_notify(alert: dict[str, Any]) -> bool:
    s = get_settings()
    rank = _SEV_RANK.get(str(alert.get("severity")), _SEV_RANK["WARN"])
    return rank >= _SEV_RANK[s.telegram_min_severity]


def on_event(type_: str, data: dict[str, Any]) -> None:
    """Hub listener: ``alert.created`` → one Telegram message. Never raises."""
    if type_ != "alert.created" or not is_enabled():
        return
    try:
        if not should_notify(data):
            return
        if not _rate_limiter().hit("telegram"):
            log.warning("Telegram: rate limit reached, alert %s not sent", data.get("type"))
            return
        _enqueue(format_alert(data))
    except Exception:  # noqa: BLE001 — a notification problem must never break the alert flow
        log.exception("Telegram: could not queue the alert")


def install(hub: Any) -> None:
    """Register the listener on the event hub (idempotent)."""
    global _installed
    if _installed:
        return
    hub.add_listener(on_event)
    _installed = True


__all__ = ["NotifyError", "format_alert", "flush", "install", "is_enabled", "on_event", "send_text",
           "should_notify"]
