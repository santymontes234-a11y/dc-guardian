import threading

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from app.core import security
from app.core.config import Settings
from app.db.session import SessionLocal
from app.models.enums import ActorType
from app.services import audit
from tests.conftest import drop_audit_triggers


def _events(db, n):
    for i in range(n):
        audit.record(db, action="test.event", actor_type=ActorType.SYSTEM, details={"i": i})
    db.commit()


# ------------------------------------------------------------------ audit chain
def test_audit_log_is_append_only_in_db(db):
    _events(db, 2)
    with pytest.raises(DatabaseError, match="append-only"):
        db.execute(text("UPDATE audit_log SET action='x' WHERE id=1"))
    db.rollback()
    with pytest.raises(DatabaseError, match="append-only"):
        db.execute(text("DELETE FROM audit_log WHERE id=1"))
    db.rollback()


def test_audit_chain_detects_tampering(db):
    _events(db, 5)
    assert audit.verify_chain(db).ok
    drop_audit_triggers(db)
    db.execute(text("UPDATE audit_log SET details_json='{\"i\": 99}' WHERE id=3"))
    db.commit()
    report = audit.verify_chain(db)
    assert not report.ok and report.broken_at_id == 3


def test_audit_chain_detects_middle_deletion(db):
    _events(db, 4)
    drop_audit_triggers(db)
    db.execute(text("DELETE FROM audit_log WHERE id=2"))
    db.commit()
    assert audit.verify_chain(db).broken_at_id == 3


def test_tail_truncation_is_visible_through_head(db):
    _events(db, 5)
    before = audit.verify_chain(db)
    drop_audit_triggers(db)
    db.execute(text("DELETE FROM audit_log WHERE id >= 4"))
    db.commit()
    after = audit.verify_chain(db)
    assert after.ok  # chain itself is consistent...
    assert after.head_id < before.head_id and after.head_hash != before.head_hash  # ...but the head moved back


def test_forged_chain_without_key_is_detected(db):
    """Recomputing hashes with plain SHA-256 (no key) must not validate."""
    import hashlib

    _events(db, 2)
    drop_audit_triggers(db)
    rows = db.execute(text("SELECT id, prev_hash FROM audit_log ORDER BY id")).all()
    forged = hashlib.sha256(b"forged").hexdigest()
    db.execute(text("UPDATE audit_log SET hash=:h WHERE id=:id"), {"h": forged, "id": rows[-1].id})
    db.commit()
    assert not audit.verify_chain(db).ok


def test_concurrent_audit_writes_keep_chain_linear():
    errors = []

    def worker(i):
        try:
            with SessionLocal() as s:
                audit.record(s, action="test.concurrent", actor_type=ActorType.SYSTEM, details={"i": i})
                s.commit()
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(repr(exc))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(25)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    with SessionLocal() as s:
        report = audit.verify_chain(s)
    assert report.ok and report.checked == 25


# ------------------------------------------------------------------ primitives
def test_password_hashing():
    h = security.hash_password("una-clave-larga")
    assert h != "una-clave-larga"
    assert security.verify_password("una-clave-larga", h)
    assert not security.verify_password("otra-clave", h)
    assert not security.verify_password("una-clave-larga", None)
    assert not security.verify_password("x" * 100, h)


def test_secret_encryption_roundtrip():
    secret = security.generate_device_secret()
    token = security.encrypt_secret(secret)
    assert secret not in token
    assert security.decrypt_secret(token) == secret


PATH = "/api/v1/device/access/abc"


def _msg(query="distance_cm=30.1", body=b""):
    return security.device_signing_string("GET", PATH, query, "1763130000", "n1", body)


def test_hmac_sign_verify():
    secret = security.generate_device_secret()
    sig = security.hmac_sign(secret, _msg())
    assert security.hmac_verify(secret, _msg(), sig)
    assert security.hmac_verify(secret, _msg(), sig.upper())
    assert not security.hmac_verify(secret, _msg(body=b"x"), sig)


def test_hmac_covers_query_string():
    secret = security.generate_device_secret()
    sig = security.hmac_sign(secret, _msg("distance_cm=30.1"))
    assert not security.hmac_verify(secret, _msg("distance_cm=999"), sig)


def test_canonical_query_is_order_independent():
    assert security.canonical_query("b=2&a=1") == security.canonical_query({"a": "1", "b": "2"}) == "a=1&b=2"
    assert security.canonical_query(None) == ""


@pytest.mark.parametrize("bad", ["\xe9" * 64, None, "", "zz" * 32, "ab" * 31, "ab" * 33, 123])
def test_hmac_verify_never_raises_on_malformed_signature(bad):
    assert security.hmac_verify("secret", b"m", bad) is False


# ------------------------------------------------------------------ config
@pytest.mark.parametrize("env", ["dev", "prod"])
def test_short_explicit_secrets_rejected(env, tmp_path):
    with pytest.raises(ValueError, match="at least"):
        Settings(env=env, data_dir=tmp_path, jwt_secret="abc", master_key="x" * 64, cookie_secure=True)


def test_prod_requires_secrets_and_secure_cookie(tmp_path):
    with pytest.raises(ValueError, match="Missing"):
        Settings(env="prod", data_dir=tmp_path, cookie_secure=True)
    with pytest.raises(ValueError, match="COOKIE_SECURE"):
        Settings(env="prod", data_dir=tmp_path, jwt_secret="a" * 64, master_key="b" * 64)
