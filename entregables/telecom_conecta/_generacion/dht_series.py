"""Sends a DHT11 series through the simulator at the firmware cadence (one reading every 10 s)."""
import httpx, sys, time, math
B = "http://127.0.0.1:8765/api/v1"; pw = open(sys.argv[1]).read().strip()
c = httpx.Client(timeout=30); c.post(B + "/auth/login", json={"username": "admin", "password": pw}).raise_for_status()
N = 90
for i in range(N):
    x = i / (N - 1)
    t = 24.0 + 9.2 * math.exp(-((x - 0.55) / 0.18) ** 2)       # CRAC failure: heats up to ~33 °C then recovers
    h = 47 + 4 * math.sin(i / 7) + (36 if 0.85 < x < 0.9 else 0)   # brief humidity spike
    if i % 15 == 0: c.post(B + "/sim/DC-DOOR-01/heartbeat")
    r = c.post(B + "/sim/DC-DOOR-01/environment", json={"temperature_c": round(t, 1), "humidity_pct": round(h, 1), "sensor": "OK"})
    print(i, round(t, 1), round(h, 1), r.status_code, flush=True)
    time.sleep(10)
