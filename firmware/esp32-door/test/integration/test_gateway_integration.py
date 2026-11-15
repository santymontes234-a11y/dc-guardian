"""Integration: real firmware core (compiled for the PC) ↔ mock gateway over HTTP.

Run from firmware/esp32-door (needs g++ and `pio test -e native` run once, which fetches
ArduinoJson into .pio/libdeps/native):

    ../../backend/.venv/bin/pytest test/integration -v

Each scenario checks the end-to-end security property it is named after.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

FW = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FW / "tools"))
import mock_gateway as mg  # noqa: E402

SECRET = secrets.token_hex(32)
BIN = FW / ".pio" / "host_runner"


@pytest.fixture(scope="session")
def runner() -> Path:
    if not shutil.which("g++"):
        pytest.skip("g++ not available")
    aj = FW / ".pio" / "libdeps" / "native" / "ArduinoJson" / "src"
    if not aj.exists():
        pytest.skip("run `pio test -e native` once to fetch ArduinoJson")
    srcs = sorted(str(p) for p in (FW / "lib" / "dcg_core" / "src").glob("*.cpp"))
    cmd = ["g++", "-std=gnu++17", "-O1", "-Wall", "-Wextra", "-pthread",
           f"-I{FW / 'lib' / 'dcg_core' / 'src'}", f"-I{aj}",
           str(FW / "test" / "host" / "host_runner.cpp"), *srcs, "-o", str(BIN)]
    subprocess.run(cmd, check=True)
    return BIN


@pytest.fixture
def gateway():
    gw = mg.Gateway(SECRET, "DC-DOOR-01", "grant", open_ms=1500, threshold_cm=50)
    srv = mg.serve(gw, "127.0.0.1", 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield gw, srv.server_address[1]
    srv.shutdown()


def run(runner: Path, port: int, seconds: int = 7, secret: str = SECRET) -> dict:
    out = subprocess.run([str(runner), "127.0.0.1", str(port), secret, str(seconds)],
                         capture_output=True, text=True, timeout=seconds + 20, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


def kinds(gw) -> list[str]:
    return [e["kind"] for e in gw.events]


# ------------------------------------------------------------------ happy path
def test_grant_opens_once_and_confirms(runner, gateway):
    gw, port = gateway
    r = run(runner, port)
    assert r["opens"] == 1
    assert r["max_angle"] == 90
    assert r["door"] == "CLOSED"  # auto-close after open_ms
    assert r["door_events"] == ["OPENED", "CLOSED:TIMER"]
    k = kinds(gw)
    assert "auth_fail" not in k
    assert k.index("start") < k.index("poll") < k.index("opened") < k.index("closed")
    start = next(e for e in gw.events if e["kind"] == "start")
    assert start["uid"] == "04A1B2C3" and start["distance_cm"] == 30
    opened = next(e for e in gw.events if e["kind"] == "opened")
    assert opened["open_ms"] == 1500
    closed = next(e for e in gw.events if e["kind"] == "closed")
    assert closed["reason"] == "TIMER"
    assert any(e["kind"] == "presence" and e["present"] for e in gw.events)
    polls = [e for e in gw.events if e["kind"] == "poll"]
    assert all(p["distance_cm"] == "30.0" for p in polls)  # signed query reached the server


# ------------------------------------------------------------------ never opens
@pytest.mark.parametrize("scenario", ["deny", "unknown", "never", "badsig", "unsigned", "replay", "othersid"])
def test_door_stays_closed(runner, gateway, scenario):
    gw, port = gateway
    gw.scenario = scenario
    r = run(runner, port, seconds=13 if scenario == "never" else 6)
    assert r["opens"] == 0, scenario
    assert r["max_angle"] == 0, scenario
    assert r["door_events"] == []
    assert "opened" not in kinds(gw)
    if scenario in ("badsig", "unsigned", "replay"):
        assert any(e["kind"] == "event" and e["type"] == "BAD_RESPONSE_SIGNATURE" for e in gw.events)


def test_wrong_device_secret_never_authenticates(runner, gateway):
    gw, port = gateway
    r = run(runner, port, seconds=4, secret=secrets.token_hex(32))
    assert r["opens"] == 0 and r["online"] is False and r["state"] == "OFFLINE"
    assert set(kinds(gw)) == {"auth_fail"}
    assert all(e["reason"] == "BAD_SIGNATURE" for e in gw.events)


def test_backend_down_is_offline_and_closed(runner, gateway):
    gw, port = gateway
    gw.scenario = "down"
    r = run(runner, port, seconds=4)
    assert r["opens"] == 0 and r["online"] is False


def test_remote_emergency_close(runner, gateway):
    gw, port = gateway
    gw.scenario = "emergency"
    gw.open_ms = 20000  # would stay open 20 s without the command
    r = run(runner, port, seconds=8)
    assert r["opens"] == 1
    assert r["door"] == "CLOSED"
    assert r["door_events"] == ["OPENED", "CLOSED:EMERGENCY"]


def test_nonces_never_repeat(runner, gateway):
    gw, port = gateway
    run(runner, port, seconds=5)
    assert len(gw.nonces) == len([e for e in gw.events if e["kind"] != "auth_fail"])


# ------------------------------------------------------------------ contract with the backend
def test_mock_signing_matches_backend_security_module():
    """The mock must sign exactly like backend/app/core/security.py (skipped if not importable)."""
    backend = FW.parents[1] / "backend"
    sys.path.insert(0, str(backend))
    try:
        import os
        os.environ.setdefault("DCG_ENV", "test")
        from app.core import security
    except Exception as exc:  # pragma: no cover - backend venv not active
        pytest.skip(f"backend not importable: {exc}")
    body = b'{"uid":"04A1B2C3","distance_cm":32.5}'
    for q in ("", "distance_cm=30.1", "b=2&a=1"):
        assert mg.request_signing_string("GET", "/api/v1/x", q, "1", "n", body) == \
            security.device_signing_string("GET", "/api/v1/x", q, "1", "n", body)
    assert mg.sign(SECRET, b"m") == security.hmac_sign(SECRET, b"m")
    fn = getattr(security, "device_response_signing_string", None)
    if fn is not None:  # added by the gateway work (F5)
        assert fn("GET", "/p", "n", 200, "1", body) == mg.response_signing_string("GET", "/p", "n", 200, "1", body)
    assert hashlib.sha256(b"").hexdigest() in mg.response_signing_string("GET", "/p", "n", 200, "1", b"").decode()
