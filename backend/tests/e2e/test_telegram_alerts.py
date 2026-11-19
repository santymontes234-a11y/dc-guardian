"""Alerts reach Telegram end to end: a real alert (unknown QR at the main entrance) → commit →
event hub → notifier → message. Telegram itself is replaced by a recorder (no network)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models import AuditLog
from app.services import notifier

SCAN = "/api/v1/kiosk/entrance/scan"
UNKNOWN_QR = "DCG-QR1:" + "A" * 32
TOKEN = "123456789:AAH_fake-token-for-tests_0123456789abc"
CHAT = "-1001234567890"


@pytest.fixture(autouse=True)
def _clean_notifier():
    notifier._limiter = None
    yield
    notifier.flush(2)
    notifier._limiter = None


@pytest.fixture(autouse=True)
def _entrance_area(f):
    return f.area("ENTRADA_PRINCIPAL")


@pytest.fixture
def telegram(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "telegram_bot_token", TOKEN)
    monkeypatch.setattr(s, "telegram_chat_id", CHAT)
    monkeypatch.setattr(s, "telegram_min_severity", "WARN")
    sent: list[str] = []
    monkeypatch.setattr(notifier, "_post", lambda token, chat, text, timeout: sent.append(text))
    return sent


@pytest.fixture
def unconfigured(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "telegram_bot_token", None)
    monkeypatch.setattr(s, "telegram_chat_id", None)


def audit_actions(db) -> list[str]:
    return [a.action for a in db.execute(select(AuditLog).order_by(AuditLog.id)).scalars()]


def test_alert_is_sent_to_telegram_after_the_commit(f, telegram):
    r = f.c.post(SCAN, json={"qr_text": UNKNOWN_QR})
    assert r.status_code == 200 and r.json()["reason_code"] == "QR_UNKNOWN"
    assert notifier.flush(3)
    assert len(telegram) == 1
    lines = telegram[0].splitlines()
    assert lines[0] == "⚠️ AVISO · Telecom Conecta" and lines[1] == "Alerta: UNKNOWN_QR"
    assert "QR denegado en la entrada principal" in telegram[0]


def test_a_repeated_alert_is_deduplicated_so_it_is_not_sent_twice(f, telegram):
    for _ in range(3):  # UNKNOWN_QR has a 60 s dedupe window
        assert f.c.post(SCAN, json={"qr_text": UNKNOWN_QR}).status_code == 200
    assert notifier.flush(3)
    assert len(telegram) == 1


def test_nothing_is_sent_when_telegram_is_not_configured(f, unconfigured, monkeypatch):
    sent = []
    monkeypatch.setattr(notifier, "_post", lambda *a: sent.append(a))
    assert f.c.post(SCAN, json={"qr_text": UNKNOWN_QR}).status_code == 200
    notifier.flush(2)
    assert sent == []


def test_notifications_status_hides_secrets_and_is_admin_only(f, telegram, auditor_api):
    out = f.ok("GET", "/api/v1/system/notifications")
    assert out == {"telegram": {"configured": True, "min_severity": "WARN", "site_name": "Telecom Conecta"}}
    assert TOKEN not in str(out) and CHAT not in str(out)
    assert auditor_api.get("/api/v1/system/notifications").status_code == 403
    assert auditor_api.post("/api/v1/system/notifications/test").status_code == 403


def test_test_message_requires_configuration(f, unconfigured):
    r = f.c.post("/api/v1/system/notifications/test")
    assert r.status_code == 409 and r.json()["error"]["code"] == "NOTIFICATIONS_NOT_CONFIGURED"


def test_test_message_is_sent_and_audited(f, telegram, db):
    assert f.ok("POST", "/api/v1/system/notifications/test") == {"sent": True}
    assert len(telegram) == 1 and "Prueba de notificaciones" in telegram[0]
    assert "notification.test_sent" in audit_actions(db)


def test_a_telegram_failure_is_reported_without_leaking_the_token(f, telegram, monkeypatch, db):
    def fail(token, chat, text, timeout):
        raise notifier.NotifyError("Telegram respondió HTTP 401 (token inválido)")

    monkeypatch.setattr(notifier, "_post", fail)
    r = f.c.post("/api/v1/system/notifications/test")
    assert r.status_code == 502 and r.json()["error"]["code"] == "NOTIFY_FAILED"
    assert TOKEN not in r.text and CHAT not in r.text
    assert "notification.test_failed" in audit_actions(db)
    assert all(TOKEN not in (a.details_json or "") for a in db.execute(select(AuditLog)).scalars())
