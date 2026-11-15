#!/usr/bin/env python3
"""Virtual ESP32 door for DC Guardian — same signed protocol as the firmware (docs/protocolo-esp32.md).

Standard library only, so it runs anywhere:

    python simulator/esp32_sim.py --url http://localhost:8000 --device DC-DOOR-01 \\
        --secret <hex64> access --uid 04A1B2C3 --distance 30

    (the secret may also come from DCG_DEVICE_SECRET)

The same class drives the E2E tests (``backend/tests/e2e``) through a pluggable transport, and
the web "Simulador" panel through the backend. Like the firmware, it rejects any response
whose signature or timestamp is invalid (fail-closed) and only "opens" on a signed GRANTED for
its own session, with a sane ``open_ms`` and local presence.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol
from urllib.parse import parse_qsl, urlencode

PREFIX = "/api/v1"
PENDING = {"CARD_READ", "AWAITING_FACE", "FACE_OK"}


# ------------------------------------------------------------------ signing (mirrors app.core.security)
def canonical_query(query: str) -> str:
    return urlencode(sorted(parse_qsl(query, keep_blank_values=True))) if query else ""


def request_signing_string(method: str, path: str, query: str, ts: str, nonce: str, body: bytes) -> bytes:
    return "\n".join([method.upper(), path, canonical_query(query), ts, nonce,
                      hashlib.sha256(body).hexdigest()]).encode()


def response_signing_string(method: str, path: str, nonce: str, status: int, ts: str, body: bytes) -> bytes:
    return "\n".join(["RESP", method.upper(), path, nonce, str(status), ts,
                      hashlib.sha256(body).hexdigest()]).encode()


def sign(secret: str, msg: bytes) -> str:
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


# ------------------------------------------------------------------ transports
class Transport(Protocol):
    def request(self, method: str, url: str, headers: dict[str, str], body: bytes) -> tuple[int, dict[str, str], bytes]:
        ...


class UrllibTransport:
    def __init__(self, base_url: str, timeout_s: float = 3.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def request(self, method, url, headers, body):
        req = urllib.request.Request(self.base_url + url, data=body if method != "GET" else None,
                                     method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read(4096 + 1)
        except urllib.error.HTTPError as e:
            return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read(4096 + 1)


class ClientTransport:
    """Adapter for any httpx-like client (e.g. FastAPI ``TestClient``)."""

    def __init__(self, client):
        self.client = client

    def request(self, method, url, headers, body):
        r = self.client.request(method, url, headers=headers, content=body if method != "GET" else None)
        return r.status_code, {k.lower(): v for k, v in r.headers.items()}, r.content


# ------------------------------------------------------------------ device
class BadResponse(Exception):
    """Unsigned / badly signed / stale response: treated exactly like a network failure."""


@dataclass
class Reply:
    status: int
    data: dict[str, Any]


@dataclass
class AccessResult:
    outcome: str  # GRANTED_AND_CLOSED | DENIED | TIMEOUT | ERROR
    state: str | None = None
    reason_code: str | None = None
    session_id: str | None = None
    open_ms: int | None = None
    log: list[str] = field(default_factory=list)


class Esp32Sim:
    def __init__(self, device_id: str, secret: str, transport: Transport, *, fw: str = "sim-1.0.0",
                 clock: Callable[[], float] = time.time, skew_s: int = 30):
        self.device_id = device_id
        self.secret = secret
        self.transport = transport
        self.fw = fw
        self.clock = clock
        self.skew_s = skew_s
        # Virtual hardware
        self.distance_cm: float = 200.0
        self.threshold_cm: int = 50
        self.door_open_ms: int = 5000
        self.heartbeat_s: int = 15
        self.door = "CLOSED"
        self.sensors = {"rfid": "OK", "ultrasonic": "OK"}
        self.session_id: str | None = None
        self.last_nonce: str | None = None
        self.tamper_response = False  # test hook: corrupt the next response check

    # --------------------------------------------------------------- low level
    def call(self, method: str, path: str, *, query: dict | None = None, body: dict | None = None,
             nonce: str | None = None, ts: int | None = None, signature: str | None = None) -> Reply:
        full_path = PREFIX + path
        qs = urlencode(query) if query else ""
        raw = json.dumps(body, separators=(",", ":")).encode() if body is not None else b""
        ts_s = str(int(ts if ts is not None else self.clock()))
        nonce = nonce or secrets.token_hex(16)
        self.last_nonce = nonce
        headers = {
            "X-Device-Id": self.device_id, "X-Timestamp": ts_s, "X-Nonce": nonce,
            "X-Signature": signature or sign(self.secret, request_signing_string(method, full_path, qs, ts_s, nonce, raw)),
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        status, rh, rbody = self.transport.request(method, full_path + (f"?{qs}" if qs else ""), headers, raw)
        self._check_response(method, full_path, nonce, status, rh, rbody)
        try:
            data = json.loads(rbody) if rbody else {}
        except ValueError as exc:
            raise BadResponse("respuesta no es JSON") from exc
        return Reply(status, data)

    def _check_response(self, method, path, nonce, status, headers, body) -> None:
        if len(body) > 4096:
            raise BadResponse("respuesta demasiado grande")
        ts, sig = headers.get("x-timestamp"), headers.get("x-signature")
        if not ts or not sig or not ts.isdigit():
            raise BadResponse(f"respuesta sin firma (HTTP {status})")
        if abs(int(self.clock()) - int(ts)) > self.skew_s:
            raise BadResponse("marca de tiempo de la respuesta fuera de ventana")
        expected = sign(self.secret, response_signing_string(method, path, nonce, status, ts, body))
        if self.tamper_response or not hmac.compare_digest(expected, sig.lower()):
            raise BadResponse("firma de respuesta inválida")

    @property
    def present(self) -> bool:
        return self.sensors.get("ultrasonic") == "OK" and 0 <= self.distance_cm <= self.threshold_cm

    @property
    def reading(self) -> float:
        return -1.0 if self.sensors.get("ultrasonic") != "OK" else round(self.distance_cm, 1)

    # --------------------------------------------------------------- endpoints
    def heartbeat(self) -> Reply:
        r = self.call("POST", "/device/heartbeat", body={
            "fw": self.fw, "state": "IDLE" if self.session_id is None else "WAITING_DECISION", "door": self.door,
            "present": self.present, "distance_cm": self.reading, "rssi": -55, "uptime_s": 1, "free_heap": 200000,
            "session_id": self.session_id, "sensors": self.sensors,
        })
        cfg = r.data.get("config") or {}
        if 2 <= int(cfg.get("presence_threshold_cm", 0) or 0) <= 400:
            self.threshold_cm = int(cfg["presence_threshold_cm"])
        if 1000 <= int(cfg.get("door_open_ms", 0) or 0) <= 30000:
            self.door_open_ms = int(cfg["door_open_ms"])
        if r.data.get("command") == "EMERGENCY_CLOSE" and self.door != "CLOSED":
            self.door = "CLOSED"
        return r

    def set_distance(self, cm: float) -> Reply | None:
        was = self.present
        self.distance_cm = cm
        if self.present != was:
            return self.call("POST", "/device/presence", body={
                "present": self.present, "distance_cm": self.reading, "threshold_cm": self.threshold_cm})
        return None

    def start(self, uid: str) -> Reply:
        r = self.call("POST", "/device/access/start", body={"uid": uid, "distance_cm": self.reading, "fw": self.fw})
        if r.data.get("state") == "GRANTED":
            raise BadResponse("GRANTED en start: una sesión nueva nunca está concedida")
        self.session_id = r.data.get("session_id")
        return r

    def poll(self, session_id: str | None = None) -> Reply:
        sid = session_id or self.session_id
        return self.call("GET", f"/device/access/{sid}", query={"distance_cm": f"{self.reading:.1f}"})

    def opened(self, session_id: str, open_ms: int) -> Reply:
        self.door = "OPEN"
        return self.call("POST", f"/device/access/{session_id}/opened", body={"open_ms": open_ms})

    def closed(self, session_id: str, reason: str = "TIMER") -> Reply:
        self.door = "CLOSED"
        r = self.call("POST", f"/device/access/{session_id}/closed", body={"reason": reason})
        if self.session_id == session_id:
            self.session_id = None
        return r

    def event(self, type_: str, detail: str | None = None) -> Reply:
        return self.call("POST", "/device/event", body={"type": type_, "detail": detail})

    # --------------------------------------------------------------- high level
    def decide(self, reply: Reply, session_id: str) -> int | None:
        """Firmware rule: open only on GRANTED for *our* session, sane open_ms, local presence."""
        d = reply.data
        if reply.status != 200 or d.get("state") != "GRANTED" or d.get("session_id") != session_id:
            return None
        open_ms = d.get("open_ms")
        if not isinstance(open_ms, int) or not 1000 <= open_ms <= 30000 or not self.present or self.door != "CLOSED":
            return None
        return open_ms

    def run_access(self, uid: str, *, between_polls: Callable[[int], None] | None = None,
                   max_polls: int = 120, poll_sleep: bool = False, close: bool = True) -> AccessResult:
        """Card read → poll until a decision → open → close. ``between_polls(i)`` lets a test or
        the CLI act meanwhile (e.g. send the face frames from the kiosk)."""
        res = AccessResult(outcome="ERROR")
        try:
            r = self.start(uid)
        except BadResponse as e:
            res.log.append(f"start: {e}")
            return res
        res.state, res.reason_code = r.data.get("state"), r.data.get("reason_code")
        sid = r.data.get("session_id")
        res.session_id = sid
        res.log.append(f"start → {res.state} {res.reason_code or ''}".strip())
        if not sid:
            res.outcome = "DENIED" if res.state == "DENIED" else "ERROR"
            return res
        poll_ms = min(max(int(r.data.get("poll_ms", 500)), 300), 2000)
        for i in range(max_polls):
            if between_polls:
                between_polls(i)
            try:
                p = self.poll(sid)
            except BadResponse as e:
                res.log.append(f"poll: {e}")
                return res
            res.state, res.reason_code = p.data.get("state"), p.data.get("reason_code")
            if res.state in PENDING:
                if poll_sleep:
                    time.sleep(poll_ms / 1000)
                continue
            res.log.append(f"poll → {res.state} {res.reason_code or ''}".strip())
            open_ms = self.decide(p, sid)
            if open_ms is None:
                res.outcome = "TIMEOUT" if res.state == "TIMEOUT" else "DENIED"
                self.session_id = None
                return res
            res.open_ms = open_ms
            self.opened(sid, open_ms)
            res.log.append(f"servo abierto {open_ms} ms")
            if close:
                if poll_sleep:
                    time.sleep(open_ms / 1000)
                self.closed(sid, "TIMER")
                res.log.append("servo cerrado")
                res.outcome = "GRANTED_AND_CLOSED"
            else:
                res.outcome = "GRANTED_OPEN"
            return res
        res.outcome = "TIMEOUT"
        return res


# ------------------------------------------------------------------ CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ESP32 virtual de DC Guardian")
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--device", default="DC-DOOR-01")
    ap.add_argument("--secret", default=os.environ.get("DCG_DEVICE_SECRET"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("heartbeat", help="enviar un latido")
    hb = sub.add_parser("run", help="latidos periódicos hasta Ctrl+C")
    hb.add_argument("--distance", type=float, default=200)
    acc = sub.add_parser("access", help="acercarse, pasar la tarjeta y esperar la decisión")
    acc.add_argument("--uid", required=True)
    acc.add_argument("--distance", type=float, default=30)
    acc.add_argument("--timeout", type=int, default=35, help="segundos esperando la decisión")
    args = ap.parse_args(argv)
    if not args.secret:
        ap.error("falta --secret (o DCG_DEVICE_SECRET)")

    dev = Esp32Sim(args.device, args.secret, UrllibTransport(args.url))
    try:
        hb = dev.heartbeat()
        print(f"heartbeat HTTP {hb.status}: {hb.data}")
        if args.cmd == "heartbeat":
            return 0
        if args.cmd == "run":
            dev.set_distance(args.distance)
            while True:
                time.sleep(dev.heartbeat_s)
                print(f"heartbeat HTTP {dev.heartbeat().status}")
        dev.set_distance(args.distance)
        print(f"presencia a {args.distance} cm (umbral {dev.threshold_cm} cm)")
        res = dev.run_access(args.uid, poll_sleep=True, max_polls=args.timeout * 2)
    except BadResponse as e:
        print(f"Respuesta rechazada (fail-closed): {e}", file=sys.stderr)
        return 2
    except (urllib.error.URLError, OSError) as e:
        print(f"Sin conexión con el backend (OFFLINE, puerta cerrada): {e}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        return 130
    for line in res.log:
        print("  " + line)
    print(f"Resultado: {res.outcome} {res.reason_code or ''}")
    return 0 if res.outcome.startswith("GRANTED") else 1


if __name__ == "__main__":
    sys.exit(main())
