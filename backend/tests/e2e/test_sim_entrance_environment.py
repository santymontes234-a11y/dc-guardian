"""Simulator panel (/sim, DCG_SIMULATION only): DHT11 reading and entrance-LED poll of the
virtual ESP32 (contrato-qr-dht11.md §5). The virtual device sends real signed requests to the
gateway; these tests need the new ``Esp32Sim.environment`` / ``entrance_poll`` methods."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.api.v1 import sim as sim_api
from app.core.errors import install_error_handlers
from app.sim import service as sim_service
from tests.e2e.conftest import esp32_sim

pytestmark = pytest.mark.skipif(
    not all(hasattr(esp32_sim.Esp32Sim, m) for m in ("environment", "entrance_poll", "entrance_led")),
    reason="simulator/esp32_sim.py todavía no implementa environment/entrance_poll (contrato §5)",
)


@pytest.fixture
def panel(api, device_client, monkeypatch):
    """A /sim app (mounted only in simulation) sharing the admin session of ``api``."""
    monkeypatch.setattr(sim_service, "transport_factory", lambda: esp32_sim.ClientTransport(device_client))
    sim_service.reset()
    app = FastAPI()

    @app.middleware("http")
    async def _cid(request: Request, call_next):
        request.state.correlation_id = "simtest00"
        return await call_next(request)

    install_error_handlers(app)
    app.include_router(sim_api.router, prefix="/api/v1")
    with TestClient(app) as c:
        c.cookies.update(api.cookies)
        yield c
    sim_service.reset()


def test_sim_environment_and_state(panel, door):
    r = panel.post("/api/v1/sim/DC-DOOR-01/environment", json={"temperature_c": 33, "humidity_pct": 50, "sensor": "OK"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["reply"]["data"] == {"ok": True, "fan": True, "alarm": True}
    assert out["device"]["fan"] is True and out["device"]["env_alarm"] is True
    assert out["device"]["last_env"]["temperature_c"] == 33
    state = panel.get("/api/v1/sim/state").json()
    dev = next(d for d in state["devices"] if d["device_code"] == "DC-DOOR-01")
    assert {"entrance_led", "fan", "env_alarm", "last_env"} <= set(dev)
    r = panel.post("/api/v1/sim/DC-DOOR-01/environment", json={"temperature_c": None, "humidity_pct": None,
                                                              "sensor": "ERROR"})
    assert r.json()["device"]["fan"] is False


def test_sim_entrance_poll_lights_the_led(panel, f, flow, door):
    f.area("ENTRADA_PRINCIPAL")
    eng, _card, _req = flow.authorized()
    text = f.ok("POST", f"/api/v1/engineers/{eng['id']}/qr", 201)["qr_text"]
    assert f.ok("POST", "/api/v1/kiosk/entrance/scan", json={"qr_text": text})["result"] == "GRANTED"
    r = panel.post("/api/v1/sim/DC-DOOR-01/entrance-poll")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["reply"]["data"]["signal"]["result"] == "GRANTED"
    assert out["device"]["entrance_led"] == "GREEN" and out["device"]["door"] == "CLOSED"
    # Delivered once: the next poll brings nothing.
    assert panel.post("/api/v1/sim/DC-DOOR-01/entrance-poll").json()["reply"]["data"] == {"signal": None}
    assert "entrance.signal_shown" in flow.audit_actions(entity="entrance_event")
