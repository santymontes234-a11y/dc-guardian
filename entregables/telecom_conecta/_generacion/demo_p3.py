"""Demo scenario for Telecom Conecta on an ISOLATED simulation server (temp DB, port 8765)."""
import httpx, sys, time, json, datetime as dt
B = "http://127.0.0.1:8765/api/v1"; pw = open(sys.argv[1]).read().strip(); OUT = sys.argv[2]
c = httpx.Client(timeout=60)
c.post(B + "/auth/login", json={"username": "admin", "password": pw}).raise_for_status()
def call(m, path, **kw):
    r = c.request(m, B + path, **kw)
    body = r.json() if r.content else None
    print(m, path, r.status_code, str(body)[:150]); return body
p = lambda path, **kw: call("POST", path, **kw)
D = "/sim/DC-DOOR-01"
p("/sim/enroll-demo-faces")
now = dt.datetime.now(dt.timezone.utc).isoformat()
def req(eng, uid, area, reason, approve=True):
    r = p("/requests", json={"engineer_id": eng, "card_uid": uid, "area_id": area, "reason": reason, "start_at": now, "duration_minutes": 120})
    if approve and r and "id" in r: p(f"/requests/{r['id']}/approve", json={"notes": "Aprobado — demostración Telecom Conecta"})
req("ENG-0002", "93F2A1D7", 1, "Acceso a recepción para mantenimiento de red")
req("ENG-0002", "93F2A1D7", 2, "Mantenimiento de switches del Servidor de clientes")
req("ENG-0001", "04A1B2C3", 1, "Turno de administración")
req("ENG-0003", "5B7C9E01", 1, "Limpieza de recepción (turno vespertino)")
req("ENG-0004", "7E3D2C1B", 1, "Visita de proveedor — revisión de CRAC", approve=False)
p(D + "/heartbeat"); p(D + "/environment", json={"temperature_c": 23.8, "humidity_pct": 46, "sensor": "OK"})
qr = {i: p(f"/engineers/{i}/qr", json={}) for i in (1, 2, 3, 4)}
def scan(text, label):
    print("--", label); p("/kiosk/entrance/scan", json={"qr_text": text}); time.sleep(0.3)
    out = p(D + "/entrance-poll"); print("   LED:", (out or {}).get("device", {}).get("entrance_led") if isinstance(out, dict) else out)
    time.sleep(1.0)
scan(qr[2]["qr_text"], "Ingeniero de red: QR válido")
scan(qr[3]["qr_text"], "Personal de limpieza: QR válido")
scan(qr[4]["qr_text"], "Proveedor: solicitud pendiente")
scan("HOLA-NO-SOY-UN-QR", "QR con formato inválido")
call("DELETE", "/engineers/1/qr")
scan(qr[1]["qr_text"], "Administrador de TI: QR revocado")
# Server room: RFID + face
def attempt(uid, mode):
    p(D + "/card", json={"uid": uid})
    out = None
    if mode:
        p(D + "/face", json={"mode": mode})
        for _ in range(8):
            out = p(D + "/poll"); d = (out or {}).get("reply", {}).get("data") or {}
            if d.get("state") in ("GRANTED", "DENIED", "TIMEOUT") or out["device"].get("door") == "OPEN": break
            time.sleep(0.6)
        if out and out["device"].get("door") == "OPEN": p(D + "/close")
    time.sleep(0.5)
attempt("93F2A1D7", "match")   # network engineer enters server room
attempt("5B7C9E01", None)      # cleaning staff denied at server room (least privilege)
attempt("0BADC0DE", None)      # unknown card
attempt("93F2A1D7", "match")   # exit
# DHT11 series
series = [24.0, 24.6, 25.3, 26.2, 27.4, 28.6, 29.8, 31.0, 32.6, 33.1, 31.2, 28.9, 26.8, 25.4, 24.7]
for t in series:
    h = 47 if t < 30 else 52
    p(D + "/environment", json={"temperature_c": t, "humidity_pct": h, "sensor": "OK"}); time.sleep(0.4)
p(D + "/environment", json={"temperature_c": 24.5, "humidity_pct": 84, "sensor": "OK"})
p(D + "/environment", json={"temperature_c": 24.4, "humidity_pct": 49, "sensor": "OK"})
# Intrusion: nobody inside, presence in front of sensor
time.sleep(16)
p(D + "/distance", json={"distance_cm": 9}); p(D + "/heartbeat"); time.sleep(1)
p(D + "/distance", json={"distance_cm": 180})
log = call("GET", "/access-log", params={"limit": 50})
alerts = call("GET", "/alerts", params={"limit": 50})
json.dump({"access_log": log, "alerts": alerts, "qr_demo": {"eng2": qr[2]["qr_text"]}}, open(OUT, "w"), ensure_ascii=False, indent=1, default=str)
