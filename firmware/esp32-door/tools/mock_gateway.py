#!/usr/bin/env python3
"""Mock of the backend device gateway (/api/v1/device/*) for firmware testing.

Independent Python implementation of docs/protocolo-esp32.md (stdlib only):
verifies the request HMAC / timestamp / nonce and signs every response bound to the
request nonce. Lets you test the real ESP32 (or the host runner) before the FastAPI
gateway exists, and inject faults the real backend never produces.

    python3 tools/mock_gateway.py --secret <64hex> [--port 8000] [--scenario grant]

Scenarios (changeable at runtime: POST /mock/scenario {"scenario": "..."} from localhost):
    grant      GRANTED after 2 polls (open_ms = --open-ms)
    deny       DENIED FACE_MISMATCH after 2 polls
    unknown    start → DENIED UNKNOWN_CARD (no session)
    never      stays AWAITING_FACE forever (device must time out)
    badsig     GRANTED but signed with a wrong key
    unsigned   GRANTED without X-Signature
    replay     answers polls with a GRANTED captured for another request (old nonce)
    othersid   GRANTED for a different session_id
    emergency  grant, then EMERGENCY_CLOSE in the next heartbeat after /opened
    down       every request gets the connection closed (simulated outage)
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlencode, urlsplit

PREFIX = "/api/v1"
SCENARIOS = ("grant", "deny", "unknown", "never", "badsig", "unsigned", "replay", "othersid",
             "emergency", "down")


def canonical_query(query: str) -> str:
    return urlencode(sorted(parse_qsl(query, keep_blank_values=True))) if query else ""


def request_signing_string(method, path, query, ts, nonce, body: bytes) -> bytes:
    return "\n".join([method.upper(), path, canonical_query(query), ts, nonce,
                      hashlib.sha256(body).hexdigest()]).encode()


def response_signing_string(method, path, req_nonce, status, ts, body: bytes) -> bytes:
    return "\n".join(["RESP", method.upper(), path, req_nonce, str(status), ts,
                      hashlib.sha256(body).hexdigest()]).encode()


def sign(secret: str, msg: bytes) -> str:
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


class Gateway:
    def __init__(self, secret: str, device_id: str, scenario: str, open_ms: int,
                 threshold_cm: int, skew_s: int = 30):
        self.secret, self.device_id = secret, device_id
        self.scenario, self.open_ms, self.threshold_cm, self.skew_s = scenario, open_ms, threshold_cm, skew_s
        self.lock = threading.Lock()
        self.nonces: set[str] = set()
        self.sessions: dict[str, dict] = {}
        self.events: list[dict] = []  # everything the device reported (for tests)
        self.pending_command: str | None = None
        self.captured: tuple[str, str, bytes] | None = None  # (ts, sig, body) for "replay"

    def log(self, kind: str, **data):
        entry = {"t": round(time.time(), 3), "kind": kind, **data}
        with self.lock:
            self.events.append(entry)
        print(json.dumps(entry, ensure_ascii=False), flush=True)

    # --------------------------------------------------------------- request auth
    def authenticate(self, h: BaseHTTPRequestHandler, path: str, query: str, body: bytes) -> str | None:
        if h.headers.get("X-Device-Id") != self.device_id:
            return "UNKNOWN_DEVICE"
        ts, nonce, sig = h.headers.get("X-Timestamp", ""), h.headers.get("X-Nonce", ""), h.headers.get("X-Signature", "")
        if not ts.isdigit() or abs(int(ts) - time.time()) > self.skew_s:
            return "BAD_TIMESTAMP"
        expected = sign(self.secret, request_signing_string(h.command, path, query, ts, nonce, body))
        if not hmac.compare_digest(expected, sig.lower()):
            return "BAD_SIGNATURE"
        with self.lock:
            if nonce in self.nonces or len(nonce) < 16:
                return "REPLAYED_NONCE"
            self.nonces.add(nonce)
        return None

    # --------------------------------------------------------------- routing
    def handle(self, method: str, path: str, query: str, body: dict) -> tuple[int, dict]:
        sub = path[len(PREFIX):]
        if sub == "/device/heartbeat" and method == "POST":
            self.log("heartbeat", **{k: body.get(k) for k in ("state", "door", "present", "distance_cm", "sensors")})
            cmd, self.pending_command = self.pending_command, None
            return 200, {"server_time": int(time.time()),
                         "config": {"presence_threshold_cm": self.threshold_cm, "door_open_ms": self.open_ms, "heartbeat_s": 15},
                         "command": cmd}
        if sub == "/device/presence" and method == "POST":
            self.log("presence", present=body.get("present"), distance_cm=body.get("distance_cm"))
            return 200, {"ok": True}
        if sub == "/device/event" and method == "POST":
            self.log("event", type=body.get("type"), detail=body.get("detail"))
            return 200, {"ok": True}
        if sub == "/device/access/start" and method == "POST":
            self.log("start", uid=body.get("uid"), distance_cm=body.get("distance_cm"))
            if self.scenario == "unknown":
                return 200, {"state": "DENIED", "reason_code": "UNKNOWN_CARD"}
            sid = secrets.token_hex(16)
            self.sessions[sid] = {"polls": 0}
            return 200, {"session_id": sid, "state": "AWAITING_FACE", "poll_ms": 500, "timeout_s": 10}
        parts = sub.split("/")  # ['', 'device', 'access', sid, (opened|closed)?]
        if len(parts) >= 4 and parts[1:3] == ["device", "access"] and parts[3] in self.sessions:
            sid, sess = parts[3], self.sessions[parts[3]]
            if len(parts) == 4 and method == "GET":
                sess["polls"] += 1
                dist = dict(parse_qsl(query)).get("distance_cm")
                self.log("poll", session_id=sid, n=sess["polls"], distance_cm=dist)
                if sess["polls"] < 2 or self.scenario == "never":
                    return 200, {"session_id": sid, "state": "AWAITING_FACE"}
                if self.scenario == "deny":
                    return 200, {"session_id": sid, "state": "DENIED", "reason_code": "FACE_MISMATCH"}
                if self.scenario == "othersid":
                    return 200, {"session_id": secrets.token_hex(16), "state": "GRANTED", "open_ms": self.open_ms}
                return 200, {"session_id": sid, "state": "GRANTED", "open_ms": self.open_ms}
            if len(parts) == 5 and parts[4] in ("opened", "closed") and method == "POST":
                self.log(parts[4], session_id=sid, **body)
                if parts[4] == "opened" and self.scenario == "emergency":
                    self.pending_command = "EMERGENCY_CLOSE"
                return 200, {"ok": True}
        return 404, {"error": {"code": "NOT_FOUND", "message": sub}}


def make_handler(gw: Gateway):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # silence default access log
            pass

        def _send(self, status: int, payload: dict, nonce: str | None, path: str):
            body = json.dumps(payload, separators=(",", ":")).encode()
            ts = str(int(time.time()))
            sig = sign(gw.secret, response_signing_string(self.command, path, nonce or "", status, ts, body)) if nonce else ""
            if nonce and gw.scenario == "badsig" and payload.get("state") == "GRANTED":
                sig = sign("f" * 64, response_signing_string(self.command, path, nonce, status, ts, body))
            if gw.scenario == "unsigned" and payload.get("state") == "GRANTED":
                sig = ""
            if gw.scenario == "replay" and payload.get("state") == "GRANTED":
                if gw.captured is None:  # capture the first one, deliver something else
                    gw.captured = (ts, sig, body)
                    payload = {"session_id": payload["session_id"], "state": "AWAITING_FACE"}
                    body = json.dumps(payload, separators=(",", ":")).encode()
                    sig = sign(gw.secret, response_signing_string(self.command, path, nonce, status, ts, body))
                else:
                    ts, sig, body = gw.captured
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Timestamp", ts)
            if sig:
                self.send_header("X-Signature", sig)
            self.end_headers()
            self.wfile.write(body)

        def _dispatch(self):
            url = urlsplit(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            if url.path == "/mock/scenario" and self.client_address[0] == "127.0.0.1":
                gw.scenario = json.loads(raw or b"{}").get("scenario", gw.scenario)
                gw.log("scenario", scenario=gw.scenario)
                return self._send(200, {"scenario": gw.scenario}, None, url.path)
            if gw.scenario == "down":
                self.close_connection = True
                return
            err = gw.authenticate(self, url.path, url.query, raw)
            if err:
                gw.log("auth_fail", reason=err, path=url.path)
                # Unknown device ⇒ no secret to sign with (as the real gateway).
                nonce = None if err == "UNKNOWN_DEVICE" else self.headers.get("X-Nonce")
                return self._send(401, {"error": {"code": "DEVICE_AUTH_FAIL", "message": err}}, nonce, url.path)
            try:
                body = json.loads(raw) if raw else {}
            except ValueError:
                return self._send(422, {"error": {"code": "BAD_JSON"}}, self.headers.get("X-Nonce"), url.path)
            status, payload = gw.handle(self.command, url.path, url.query, body)
            self._send(status, payload, self.headers.get("X-Nonce"), url.path)

        do_GET = do_POST = _dispatch

    return Handler


def serve(gw: Gateway, host: str, port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(gw))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--secret", required=True, help="64 hex chars, same as DCG_DEVICE_SECRET")
    ap.add_argument("--device-id", default="DC-DOOR-01")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--scenario", choices=SCENARIOS, default="grant")
    ap.add_argument("--open-ms", type=int, default=5000)
    ap.add_argument("--threshold-cm", type=int, default=50)
    a = ap.parse_args()
    gw = Gateway(a.secret, a.device_id, a.scenario, a.open_ms, a.threshold_cm)
    srv = serve(gw, a.host, a.port)
    print(f"mock gateway on {a.host}:{a.port} scenario={a.scenario}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
