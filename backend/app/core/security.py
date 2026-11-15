"""Cryptographic primitives: password hashing, JWT, secrets-at-rest encryption, HMAC helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlencode

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings

# bcrypt only uses the first 72 bytes; reject longer inputs instead of silently truncating.
MAX_PASSWORD_BYTES = 72

# A real hash used to equalize timing when the username does not exist.
_DUMMY_HASH = bcrypt.hashpw(b"dc-guardian-timing-equalizer", bcrypt.gensalt()).decode()


# ---------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    raw = password.encode()
    if len(raw) > MAX_PASSWORD_BYTES:
        raise ValueError("Password too long")
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, password_hash: str | None) -> bool:
    raw = password.encode()
    if len(raw) > MAX_PASSWORD_BYTES:
        bcrypt.checkpw(b"x", _DUMMY_HASH.encode())
        return False
    target = (password_hash or _DUMMY_HASH).encode()
    ok = bcrypt.checkpw(raw, target)
    return ok and password_hash is not None


# ---------------------------------------------------------------- JWT
def create_access_token(subject: str, role: str, token_version: int) -> tuple[str, datetime]:
    s = get_settings()
    now = datetime.now(UTC)
    exp = now + timedelta(minutes=s.jwt_expire_minutes)
    payload = {
        "sub": subject,
        "role": role,
        "tv": token_version,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "iss": "dc-guardian",
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm), exp


def decode_access_token(token: str) -> dict:
    """Raises ``jwt.PyJWTError`` on any problem (bad signature, expired, wrong issuer...)."""
    s = get_settings()
    return jwt.decode(
        token,
        s.jwt_secret,
        algorithms=[s.jwt_algorithm],
        issuer="dc-guardian",
        options={"require": ["sub", "exp", "iat", "iss", "tv"]},
    )


# ---------------------------------------------------------------- secrets at rest
def _fernet() -> Fernet:
    key = hashlib.sha256(get_settings().master_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:  # wrong master key or tampered value
        raise ValueError("Cannot decrypt secret") from exc


# ---------------------------------------------------------------- biometric data at rest
def _biometric_fernet() -> Fernet:
    # Separate key (domain-separated derivation) so device secrets and biometrics never share one.
    key = hashlib.sha256(b"dcg-biometric-v1\x00" + get_settings().master_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_biometric(data: bytes) -> bytes:
    return _biometric_fernet().encrypt(data)


def decrypt_biometric(token: bytes) -> bytes:
    try:
        return _biometric_fernet().decrypt(token)
    except InvalidToken as exc:
        raise ValueError("Cannot decrypt biometric data") from exc


def generate_device_secret() -> str:
    return secrets.token_hex(32)


# ---------------------------------------------------------------- HMAC (device protocol)
_HEX64 = re.compile(r"[0-9a-fA-F]{64}")


def canonical_query(query: str | Mapping[str, str] | None) -> str:
    """Sorted ``k=v&k2=v2`` (percent-encoded), so device and server sign identical bytes."""
    if not query:
        return ""
    pairs = parse_qsl(query, keep_blank_values=True) if isinstance(query, str) else list(query.items())
    return urlencode(sorted(pairs))


def device_signing_string(
    method: str, path: str, query: str | Mapping[str, str] | None, timestamp: str, nonce: str, body: bytes
) -> bytes:
    """``METHOD\\nPATH\\nCANONICAL_QUERY\\nTIMESTAMP\\nNONCE\\nSHA256(BODY)``.

    The query string is signed too: it carries decision data (e.g. ``distance_cm``).
    """
    body_hash = hashlib.sha256(body).hexdigest()
    return "\n".join([method.upper(), path, canonical_query(query), timestamp, nonce, body_hash]).encode()


def device_response_signing_string(
    method: str, path: str, request_nonce: str, status: int, timestamp: str, body: bytes
) -> bytes:
    """``RESP\nMETHOD\nPATH\nREQUEST_NONCE\nSTATUS\nTIMESTAMP\nSHA256(BODY)`` (docs/protocolo-esp32.md §2.2).

    Binding the request nonce means a captured ``GRANTED`` cannot be replayed into another poll.
    """
    body_hash = hashlib.sha256(body).hexdigest()
    return "\n".join(["RESP", method.upper(), path, request_nonce, str(status), timestamp, body_hash]).encode()


def hmac_sign(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def hmac_verify(secret: str, message: bytes, signature: str | None) -> bool:
    """Never raises: malformed signatures (non-hex, wrong length, None) simply fail."""
    if not isinstance(signature, str) or not _HEX64.fullmatch(signature):
        return False
    return hmac.compare_digest(hmac_sign(secret, message).encode(), signature.lower().encode())
