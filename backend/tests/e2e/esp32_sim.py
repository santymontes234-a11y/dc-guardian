#!/usr/bin/env python3
"""Protocol client of an ESP32 door for the E2E tests — same signed protocol as the firmware
(docs/protocolo-esp32.md).

Test helper only (standard library): it plays the device side of the HMAC protocol against the
real gateway through ``ClientTransport`` (FastAPI ``TestClient``). The product has no virtual
device: the door is the physical ESP32. Like the firmware, it rejects any response whose
signature or timestamp is invalid (fail-closed) and only "opens" on a signed GRANTED for its
own session, with a sane ``open_ms`` and local presence.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol
from urllib.parse import parse_qsl, urlencode

PREFIX = "/api/v1"
PENDING = {"CARD_READ", "AWAITING_FACE", "FACE_OK"}

# Main entrance (QR) and DHT11 — docs/contrato-qr-dht11.md, protocolo-esp32.md §10/§11.
SIGNAL_ID = re.compile(r"[0-9a-f]{32}")
ENTRANCE_LED_MS = (1000, 10000)
ENTRANCE_DENIED_S = 3.0  # red blink + LCD "QR DENEGADO" (the LCD message lasts 3 s)
FAN_HYSTERESIS_C = 1.0
ENV_DEFAULTS = {"temp_high_c": 27.0, "temp_critical_c": 32.0, "humidity_low_pct": 20.0, "humidity_high_pct": 80.0}


def lcd_text(value: Any, max_len: int) -> str:
    """Untrusted text for the HD44780: printable ASCII only, truncated (firmware sanitizeLcdText)."""
    if not isinstance(value, str):
        return ""
    return "".join(c for c in value if 0x20 <= ord(c) < 0x7F)[:max_len]


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else None


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
        self.sensors = {"rfid": "OK", "ultrasonic": "OK", "dht": "OK"}
        self.session_id: str | None = None
        self.button_session = False  # current session was started by the inside exit button
        self.lcd: tuple[str, str] | None = None  # (greeting, name) of the last GRANTED
        self.alarm_s = 0  # last intrusion alarm requested by the backend (seconds)
        # DHT11 / fan / environmental alarm (§11)
        self.env_thresholds: dict[str, float] = dict(ENV_DEFAULTS)
        self.fan = False
        self.env_alarm = False
        self.env_local = True  # True: fan/alarm decided locally (no valid signed reply)
        self.last_env: dict[str, Any] | None = None  # last reading sent {temperature_c, humidity_pct, sensor, at}
        self._local_fan = False  # hysteresis memory of the local decision
        # Main entrance LED (§10): "GREEN" / "RED_BLINK" until _entrance_until (clock seconds)
        self._entrance_led: str | None = None
        self._entrance_until = 0.0
        self.last_entrance: dict[str, Any] | None = None  # last signal shown {id, result, display_name}
        self.last_entrance_ack_error: str | None = None
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
        self._apply_env_config(cfg)
        if r.data.get("command") == "EMERGENCY_CLOSE" and self.door != "CLOSED":
            self.door = "CLOSED"
        return r

    def set_distance(self, cm: float) -> Reply | None:
        """Someone moves in front of the INSIDE sensor. The reply may ask for the intrusion
        alarm (``alarm: true``), which the virtual device records in ``self.alarm_s``."""
        was = self.present
        self.distance_cm = cm
        if self.present != was:
            r = self.call("POST", "/device/presence", body={
                "present": self.present, "distance_cm": self.reading, "threshold_cm": self.threshold_cm})
            if self.present and r.data.get("alarm"):
                self.alarm_s = int(r.data.get("alarm_s") or 20)
            return r
        return None

    def start(self, uid: str) -> Reply:
        r = self.call("POST", "/device/access/start", body={"uid": uid, "distance_cm": self.reading, "fw": self.fw})
        if r.data.get("state") == "GRANTED":
            raise BadResponse("GRANTED en start: una sesión nueva nunca está concedida")
        self.session_id = r.data.get("session_id")
        self.button_session = False
        return r

    def exit_button(self) -> Reply:
        """Inside exit button: the backend opens only if someone is inside this door."""
        r = self.call("POST", "/device/exit-button", body={"source": "BUTTON"})
        if r.data.get("state") == "GRANTED":
            raise BadResponse("GRANTED en exit-button: la decisión llega por el poll")
        self.session_id = r.data.get("session_id")
        self.button_session = bool(self.session_id)
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
            self.button_session = False
        return r

    def event(self, type_: str, detail: str | None = None) -> Reply:
        return self.call("POST", "/device/event", body={"type": type_, "detail": detail})

    # --------------------------------------------------------------- DHT11 (§11)
    def _apply_env_config(self, cfg: dict) -> None:
        """Same rules as the firmware: each pair is accepted only in range and consistent."""
        th = self.env_thresholds
        hi = _num(cfg.get("temp_high_c")) if "temp_high_c" in cfg else th["temp_high_c"]
        crit = _num(cfg.get("temp_critical_c")) if "temp_critical_c" in cfg else th["temp_critical_c"]
        if hi is not None and crit is not None and 15 <= hi <= 45 and 15 <= crit <= 50 and crit > hi:
            th["temp_high_c"], th["temp_critical_c"] = hi, crit
        lo = _num(cfg.get("humidity_low_pct")) if "humidity_low_pct" in cfg else th["humidity_low_pct"]
        hh = _num(cfg.get("humidity_high_pct")) if "humidity_high_pct" in cfg else th["humidity_high_pct"]
        if lo is not None and hh is not None and 0 <= lo <= 100 and 0 <= hh <= 100 and hh > lo:
            th["humidity_low_pct"], th["humidity_high_pct"] = lo, hh

    def _local_env(self, t: float | None, h: float | None) -> tuple[bool, bool]:
        """Local fallback (backend unreachable / bad signature): fan with 1 °C hysteresis on
        temp_high_c; alarm on temp_critical_c or humidity out of range. Sensor ERROR ⇒ both off."""
        th = self.env_thresholds
        if t is None or h is None:
            self._local_fan = False
            return False, False
        if t >= th["temp_high_c"]:
            self._local_fan = True
        elif t < th["temp_high_c"] - FAN_HYSTERESIS_C:
            self._local_fan = False
        alarm = t >= th["temp_critical_c"] or h < th["humidity_low_pct"] or h > th["humidity_high_pct"]
        return self._local_fan, alarm

    def environment(self, temperature_c: float | None, humidity_pct: float | None, sensor: str = "OK") -> Reply:
        """One DHT11 report (``POST /device/environment``) and the signed ``{fan, alarm}`` applied.

        Like the firmware: ``sensor="OK"`` without both values counts as ``ERROR``; with the
        sensor in ERROR the fan is off; if the reply is unsigned/forged/malformed or the backend
        is unreachable, fan and alarm are decided locally and the error is re-raised."""
        t, h = _num(temperature_c), _num(humidity_pct)
        ok = sensor == "OK" and t is not None and h is not None
        t, h = (round(t, 1), round(h, 1)) if ok else (None, None)
        body = {"temperature_c": t, "humidity_pct": h, "sensor": "OK" if ok else "ERROR"}
        self.sensors["dht"] = body["sensor"]
        self.last_env = {**body, "at": self.clock()}
        local_fan, local_alarm = self._local_env(t, h)
        try:
            r = self.call("POST", "/device/environment", body=body)
            fan, alarm = r.data.get("fan"), r.data.get("alarm")
            if r.status == 200 and not (isinstance(fan, bool) and isinstance(alarm, bool)):
                raise BadResponse("respuesta de entorno sin fan/alarm booleanos")
        except (BadResponse, OSError):
            self.fan, self.env_alarm, self.env_local = local_fan, local_alarm, True
            raise
        if r.status != 200:  # signed error: same local fallback, the reply is returned as is
            self.fan, self.env_alarm, self.env_local = local_fan, local_alarm, True
            return r
        self.env_local = False
        self.fan = ok and (fan or local_fan)  # sensor ERROR ⇒ off; when in doubt, cool
        self.env_alarm = alarm
        return r

    # --------------------------------------------------------------- main entrance (§10)
    @property
    def entrance_led(self) -> str:
        """``"GREEN"`` (QR granted, during led_ms), ``"RED_BLINK"`` (denied) or ``"OFF"``."""
        if self._entrance_led and self.clock() < self._entrance_until:
            return self._entrance_led
        return "OFF"

    @property
    def entrance_led_until(self) -> float | None:
        """Epoch seconds when the current entrance LED pattern ends (None if off)."""
        return self._entrance_until if self.entrance_led != "OFF" else None

    def entrance_poll(self) -> Reply:
        """``POST /device/entrance/poll``: a pending QR signal is shown (entrance LED) and then
        acknowledged. Malformed signals are ignored (LED unchanged); the room servo never moves."""
        r = self.call("POST", "/device/entrance/poll", body={})
        if r.status != 200:
            return r
        sig = r.data.get("signal")
        if sig is None:
            return r
        if not isinstance(sig, dict):
            raise BadResponse("señal de entrada con formato inválido")
        sid = sig.get("id")
        if not isinstance(sid, str) or not SIGNAL_ID.fullmatch(sid):
            raise BadResponse("id de señal inválido")
        result = sig.get("result")
        led_ms = sig.get("led_ms", 5000)
        name = lcd_text(sig.get("display_name"), 40)
        if result == "GRANTED":
            if not isinstance(led_ms, int) or isinstance(led_ms, bool) or not ENTRANCE_LED_MS[0] <= led_ms <= ENTRANCE_LED_MS[1]:
                raise BadResponse("led_ms fuera de rango")
            if self.last_entrance and self.last_entrance.get("id") == sid:
                return r  # never shown twice
            self._entrance_led, self._entrance_until = "GREEN", self.clock() + led_ms / 1000
        elif result == "DENIED":
            if self.last_entrance and self.last_entrance.get("id") == sid:
                return r
            self._entrance_led, self._entrance_until = "RED_BLINK", self.clock() + ENTRANCE_DENIED_S
        else:
            return r  # unknown result: ignored, not acknowledged
        self.last_entrance = {"id": sid, "result": result, "display_name": name,
                              "led_ms": led_ms if result == "GRANTED" else None}
        self.last_entrance_ack_error = None
        try:
            self.call("POST", f"/device/entrance/{sid}/ack", body={"shown": True})
        except (BadResponse, OSError) as e:  # the signal was already shown; the ack is best effort
            self.last_entrance_ack_error = str(e)
        return r

    # --------------------------------------------------------------- high level
    def decide(self, reply: Reply, session_id: str) -> int | None:
        """Firmware rule: open only on GRANTED for *our* session, sane open_ms, local presence."""
        d = reply.data
        if reply.status != 200 or d.get("state") != "GRANTED" or d.get("session_id") != session_id:
            return None
        open_ms = d.get("open_ms")
        # The HC-SR04 is inside the room (intrusion alarm): it is not an access factor.
        if not isinstance(open_ms, int) or not 1000 <= open_ms <= 30000 or self.door != "CLOSED":
            return None
        self.lcd = (str(d.get("greeting") or "Bienvenido"), str(d.get("display_name") or ""))
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
