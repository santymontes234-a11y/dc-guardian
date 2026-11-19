"""Telegram notifier: configuration rules, message format, filtering, rate cap and error handling.

Pure logic, no database and no network: ``notifier._post`` is replaced by a recorder and
``urllib`` is stubbed where the transport itself is tested."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.services import notifier

TOKEN = "123456789:AAH_fake-token-for-tests_0123456789abc"
CHAT = "-1001234567890"
ALERT = {"id": 1, "type": "INTRUSION", "severity": "CRITICAL", "message": "Intrusión en la sala de servidores",
         "created_at": "2026-11-19T14:05:09+00:00"}


def make_settings(**over) -> Settings:
    return Settings(_env_file=None, env="test", **over)


@pytest.fixture(autouse=True)
def clean_notifier():
    notifier._limiter = None
    yield
    notifier.flush(2)
    notifier._limiter = None


@pytest.fixture
def telegram(monkeypatch):
    """Telegram configured; messages recorded instead of sent."""
    s = get_settings()
    monkeypatch.setattr(s, "telegram_bot_token", TOKEN)
    monkeypatch.setattr(s, "telegram_chat_id", CHAT)
    monkeypatch.setattr(s, "telegram_min_severity", "WARN")
    monkeypatch.setattr(s, "telegram_rate_per_minute", 20)
    sent: list[tuple[str, str, str]] = []
    monkeypatch.setattr(notifier, "_post", lambda token, chat, text, timeout: sent.append((token, chat, text)))
    return sent


# ------------------------------------------------------------------ configuration
def test_disabled_by_default_and_blank_values_mean_unset():
    s = make_settings()
    assert s.telegram_bot_token is None and s.telegram_chat_id is None
    blank = make_settings(telegram_bot_token="  ", telegram_chat_id="")
    assert blank.telegram_bot_token is None and blank.telegram_chat_id is None


def test_token_and_chat_must_come_together():
    with pytest.raises(ValidationError) as e:
        make_settings(telegram_bot_token=TOKEN)
    assert "together" in str(e.value) and TOKEN not in str(e.value)
    with pytest.raises(ValidationError):
        make_settings(telegram_chat_id=CHAT)


@pytest.mark.parametrize("token", ["abc", "123456:short", "notdigits:" + "A" * 35, "1234567890123:" + "A" * 35])
def test_bad_token_format_is_rejected_without_echoing_it(token):
    with pytest.raises(ValidationError) as e:
        make_settings(telegram_bot_token=token, telegram_chat_id=CHAT)
    assert token not in str(e.value)


@pytest.mark.parametrize("chat", ["abc", "12 34", "@ab", "-", "1" * 25])
def test_bad_chat_id_is_rejected(chat):
    with pytest.raises(ValidationError):
        make_settings(telegram_bot_token=TOKEN, telegram_chat_id=chat)


@pytest.mark.parametrize("chat", ["123456789", "-1001234567890", "@dc_alertas"])
def test_valid_chat_ids(chat):
    assert make_settings(telegram_bot_token=TOKEN, telegram_chat_id=chat).telegram_chat_id == chat


# ------------------------------------------------------------------ message
def test_format_alert_is_plain_text_with_site_severity_type_and_time():
    text = notifier.format_alert(ALERT, site="Telecom Conecta")
    assert text.splitlines() == ["🚨 CRÍTICA · Telecom Conecta", "Alerta: INTRUSION",
                                 "Intrusión en la sala de servidores", "2026-11-19 14:05:09 UTC"]


def test_format_alert_is_capped_and_tolerates_odd_input():
    long = notifier.format_alert({"type": "X", "severity": "WARN", "message": "m" * 5000}, site="S")
    assert len(long) == notifier.MAX_TEXT
    odd = notifier.format_alert({"type": "X", "severity": "??", "created_at": "not-a-date"}, site="S")
    assert "?? · S" in odd and "not-a-date" in odd


# ------------------------------------------------------------------ filtering and delivery
def test_critical_alert_is_sent_once_to_the_configured_chat(telegram):
    notifier.on_event("alert.created", ALERT)
    assert notifier.flush(2)
    assert len(telegram) == 1
    token, chat, text = telegram[0]
    assert (token, chat) == (TOKEN, CHAT) and "INTRUSION" in text


def test_other_event_types_are_ignored(telegram):
    for t in ("alert.acknowledged", "access.granted", "environment", "entrance.scan"):
        notifier.on_event(t, ALERT)
    notifier.flush(2)
    assert telegram == []


def test_min_severity_filters(telegram, monkeypatch):
    info = {**ALERT, "severity": "INFO"}
    warn = {**ALERT, "severity": "WARN"}
    notifier.on_event("alert.created", info)  # below WARN
    notifier.on_event("alert.created", warn)
    monkeypatch.setattr(get_settings(), "telegram_min_severity", "CRITICAL")
    notifier.on_event("alert.created", warn)  # below CRITICAL
    notifier.on_event("alert.created", ALERT)
    notifier.flush(2)
    first_lines = [t.splitlines()[0] for _, _, t in telegram]
    assert first_lines == ["⚠️ AVISO · Telecom Conecta", "🚨 CRÍTICA · Telecom Conecta"]


def test_nothing_is_sent_when_not_configured(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "telegram_bot_token", None)
    monkeypatch.setattr(s, "telegram_chat_id", None)
    called = []
    monkeypatch.setattr(notifier, "_post", lambda *a: called.append(a))
    notifier.on_event("alert.created", ALERT)
    notifier.flush(1)
    assert called == [] and notifier.is_enabled() is False
    with pytest.raises(notifier.NotifyError, match="no está configurado"):
        notifier.send_text("hola")


def test_rate_cap_drops_the_excess(telegram, monkeypatch):
    monkeypatch.setattr(get_settings(), "telegram_rate_per_minute", 2)
    for _ in range(5):
        notifier.on_event("alert.created", ALERT)
    notifier.flush(2)
    assert len(telegram) == 2


def test_a_failing_send_does_not_stop_the_next_ones(monkeypatch, telegram):
    calls: list[str] = []

    def flaky(token, chat, text, timeout):
        calls.append(text)
        if len(calls) == 1:
            raise notifier.NotifyError("boom")

    monkeypatch.setattr(notifier, "_post", flaky)
    notifier.on_event("alert.created", ALERT)
    notifier.on_event("alert.created", {**ALERT, "type": "TEMPERATURA_ALTA", "severity": "WARN"})
    assert notifier.flush(2)
    assert len(calls) == 2 and "TEMPERATURA_ALTA" in calls[1]


def test_on_event_never_raises(telegram, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("formatter exploded")

    monkeypatch.setattr(notifier, "format_alert", broken)
    notifier.on_event("alert.created", ALERT)  # logged, not raised


def test_install_registers_the_listener_once():
    class FakeHub:
        def __init__(self):
            self.listeners = []

        def add_listener(self, fn):
            self.listeners.append(fn)

    notifier._installed = False
    hub = FakeHub()
    notifier.install(hub)
    notifier.install(hub)
    assert hub.listeners == [notifier.on_event]


# ------------------------------------------------------------------ transport
class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_post_sends_json_to_the_bot_endpoint(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen.update(url=req.full_url, body=json.loads(req.data), timeout=timeout, method=req.get_method())
        return FakeResponse(b'{"ok": true}')

    monkeypatch.setattr(notifier.urllib.request, "urlopen", fake_urlopen)
    notifier._post(TOKEN, CHAT, "hola", 5)
    assert seen["url"] == f"https://api.telegram.org/bot{TOKEN}/sendMessage" and seen["method"] == "POST"
    assert seen["body"] == {"chat_id": CHAT, "text": "hola", "disable_web_page_preview": True}
    assert "parse_mode" not in seen["body"] and seen["timeout"] == 5


@pytest.mark.parametrize("code,hint", [(401, "token inválido"), (400, "chat id"), (403, "bloqueado")])
def test_http_errors_become_notify_errors_without_the_token(monkeypatch, code, hint):
    def boom(req, timeout):
        raise urllib.error.HTTPError(req.full_url, code, "x", {}, None)

    monkeypatch.setattr(notifier.urllib.request, "urlopen", boom)
    with pytest.raises(notifier.NotifyError) as e:
        notifier._post(TOKEN, CHAT, "x", 5)
    assert str(code) in str(e.value) and hint in str(e.value) and TOKEN not in str(e.value)


def test_network_errors_and_bad_payloads_become_notify_errors(monkeypatch):
    def down(req, timeout):
        raise urllib.error.URLError(f"unreachable {req.full_url}")

    monkeypatch.setattr(notifier.urllib.request, "urlopen", down)
    with pytest.raises(notifier.NotifyError) as e:
        notifier._post(TOKEN, CHAT, "x", 5)
    assert TOKEN not in str(e.value) and TOKEN not in repr(e.value)

    monkeypatch.setattr(notifier.urllib.request, "urlopen", lambda req, timeout: FakeResponse(b"<html>"))
    with pytest.raises(notifier.NotifyError, match="no válida"):
        notifier._post(TOKEN, CHAT, "x", 5)
    monkeypatch.setattr(notifier.urllib.request, "urlopen", lambda req, timeout: FakeResponse(b'{"ok": false}'))
    with pytest.raises(notifier.NotifyError, match="no aceptó"):
        notifier._post(TOKEN, CHAT, "x", 5)
