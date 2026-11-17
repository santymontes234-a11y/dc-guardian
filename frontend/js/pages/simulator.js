import { ready } from "/js/layout.js";
import { api, escapeHtml, guarded, toast } from "/js/api.js";
import { $, reasonText } from "/js/ui.js";

await ready;

let code = null;
let dev = null;
let pollTimer = null;
let closeTimer = null;
let entranceTimer = null;
let entranceAuto = null;

function log(text, tone = "", detail = null) {
  const li = document.createElement("li");
  if (tone) li.className = tone;
  li.innerHTML = escapeHtml(text) + (detail ? ` <span class="muted">${escapeHtml(detail)}</span>` : "");
  $("log").prepend(li);
}

function setDecision(text, tone = "muted") {
  $("decision").className = `badge badge-${tone}`;
  $("decision").textContent = text;
}

function renderDevice(d) {
  if (!d) return;
  dev = d;
  $("dist-label").textContent = d.sensors.ultrasonic === "OK" ? `${Math.round(d.distance_cm)} cm` : "sin lectura";
  $("thr-label").textContent = `(umbral ${d.threshold_cm} cm)`;
  $("distance").value = Math.round(d.distance_cm);
  $("online").checked = d.online;
  $("sensor-ok").checked = d.sensors.ultrasonic === "OK";
  $("presence").className = `badge badge-${d.present ? "ok" : "muted"}`;
  $("presence").textContent = d.present ? "Persona presente" : "Sin presencia";
  const open = d.door === "OPEN";
  $("door-leaf").classList.toggle("open", open);
  $("door-state").className = `badge badge-${open ? "ok" : "muted"}`;
  $("door-state").textContent = open ? "ABIERTA" : "CERRADA";
  $("hw-status").textContent = d.online ? "" : "Desconectado: no envía latidos";
  const awaiting = Boolean(d.session_id) && !open;
  document.querySelectorAll("[data-face]").forEach((b) => { b.disabled = !awaiting; });
  renderEnvironment(d);
  if ("entrance_led" in d) {
    // Solo se reacciona a cambios del estado del ESP32 virtual; el apagado lo marca el temporizador
    // local (led_ms) para no volver a encender un LED ya vencido en el siguiente refresco.
    const led = d.entrance_led && d.entrance_led !== "OFF" ? d.entrance_led : null;
    const until = parseUntil(d.entrance_led_until ?? d.entrance_led_expires_at);
    if (led !== serverLed) {
      serverLed = led;
      if (!led || (until !== null && until <= Date.now())) applyEntrance(null);
      else applyEntrance(led, until ?? Date.now() + (led === "GREEN" ? 5000 : 3000));
    }
  }
}

// ------------------------------------------------------------------ entrada principal (LED)
let serverLed = null;

function parseUntil(v) {
  if (v === null || v === undefined) return null;
  if (typeof v === "number") return v > 1e12 ? v : v > 1e9 ? v * 1000 : null;
  const t = Date.parse(v);
  return Number.isFinite(t) ? t : null;
}

function applyEntrance(led, until = null) {
  clearTimeout(entranceTimer);
  const green = led === "GREEN";
  const red = led === "RED_BLINK";
  $("sim-led-green").classList.toggle("on", green);
  $("sim-led-green-state").textContent = green ? "Encendido · puerta abierta" : "Apagado";
  $("sim-led-red").classList.toggle("blink-loop", red);
  $("sim-led-red-state").textContent = red ? "Parpadeando · denegado" : "Apagado";
  if (led && until) entranceTimer = setTimeout(() => applyEntrance(null), Math.max(0, until - Date.now()));
}

// ------------------------------------------------------------------ DHT11
function renderEnvironment(d) {
  if ("fan" in d) {
    $("sim-fan-icon").classList.toggle("on", Boolean(d.fan));
    $("sim-fan-state").textContent = d.fan ? "Encendido" : "Apagado";
  }
  if ("env_alarm" in d) {
    $("sim-env-alarm").classList.toggle("blink-loop", Boolean(d.env_alarm));
    $("sim-env-alarm-state").textContent = d.env_alarm ? "ACTIVA" : "Inactiva";
  }
  const e = d.last_env;
  if (e) {
    $("sim-last-env").textContent = e.sensor === "ERROR" || e.sensor_ok === false
      ? "Última lectura: sensor con fallo (ERROR)"
      : `Última lectura enviada: ${fmtNum(e.temperature_c)} °C · ${fmtNum(e.humidity_pct)} %`;
  }
}

const fmtNum = (v) => (v === null || v === undefined || !Number.isFinite(Number(v)) ? "—" : Number(v).toFixed(1));

function describe(reply) {
  if (!reply) return null;
  if (reply.error) return reply.error;
  const d = reply.data ?? {};
  if (d.error) return `HTTP ${reply.status} ${d.error.code}: ${d.error.message}`;
  return `HTTP ${reply.status} ${JSON.stringify(d)}`;
}

async function act(path, body = {}) {
  const out = await guarded(() => api.post(`/sim/${code}${path}`, body));
  if (out?.device) renderDevice(out.device);
  return out;
}

function stopPolling() { clearInterval(pollTimer); pollTimer = null; }

function startPolling() {
  stopPolling();
  pollTimer = setInterval(async () => {
    const out = await act("/poll");
    const data = out?.reply?.data;
    if (!out || out.reply?.error) { stopPolling(); if (out) log(out.reply.error, "danger"); return; }
    const state = data?.state;
    if (["CARD_READ", "AWAITING_FACE", "FACE_OK"].includes(state)) return;
    stopPolling();
    if (state === "GRANTED" && out.device.door === "OPEN") {
      setDecision("ACCESO CONCEDIDO", "ok");
      log(`Respuesta GRANTED firmada válida → el servo abre ${data.open_ms} ms`, "ok", describe(out.reply));
      clearTimeout(closeTimer);
      closeTimer = setTimeout(async () => {
        const c = await act("/close");
        if (c) log("Servo cerrado por temporizador; cierre registrado", "ok");
        setDecision("Sin intento");
      }, data.open_ms);
    } else {
      const reason = data?.reason_code;
      setDecision(`DENEGADO: ${reason ?? state}`, "danger");
      log(`Decisión: ${state}${reason ? ` (${reasonText(reason)})` : ""}. La puerta no se abre.`, "danger",
        describe(out.reply));
    }
  }, 700);
}

async function loadState() {
  const st = await guarded(() => api.get("/sim/state"));
  if (!st) return;
  const sel = $("device");
  if (!sel.options.length) {
    sel.innerHTML = st.devices.map((d) => `<option>${escapeHtml(d.device_code)}</option>`).join("");
    code = st.devices[0]?.device_code ?? null;
  }
  const chosen = $("card").value;
  $("card").innerHTML = '<option value="">— elegir —</option>' + st.cards.map((c) => {
    const who = c.engineer ? `${c.engineer.full_name} (${c.engineer.engineer_id}, ${c.engineer.status})` : "sin asignar";
    return `<option value="${escapeHtml(c.uid)}">${escapeHtml(c.uid)} · ${escapeHtml(who)} · ${escapeHtml(c.status)}</option>`;
  }).join("");
  $("card").value = chosen;
  const d = st.devices.find((x) => x.device_code === code);
  renderDevice(d);
  if (!code) toast("No hay dispositivos: crea uno o ejecuta la semilla", "error");
  $("kiosk-link").href = `/pages/kiosk.html?device=${encodeURIComponent(code ?? "")}`;
  $("entrance-link").href = `/pages/entrance.html?device=${encodeURIComponent(code ?? "")}`;
}

$("device").addEventListener("change", (e) => { code = e.target.value; stopPolling(); loadState(); });

let distTimer = null;
$("distance").addEventListener("input", (e) => {
  $("dist-label").textContent = `${e.target.value} cm`;
  clearTimeout(distTimer);
  distTimer = setTimeout(async () => {
    const out = await act("/distance", { distance_cm: Number(e.target.value) });
    if (out?.reply?.data?.alarm) log(`ALARMA DE INTRUSIÓN: persona dentro de la sala sin nadie autorizado (${out.reply.data.alarm_s} s de zumbador y LED rojo)`, "danger", describe(out.reply));
    else if (out?.reply?.data) log(`Sensor interior: ${out.device.present ? "persona en la sala" : "sala vacía"} (${e.target.value} cm)`, "", describe(out.reply));
  }, 250);
});
async function moveInside(cm) {
  const out = await act("/distance", { distance_cm: cm });
  if (!out) return;
  if (out.reply?.data?.alarm) {
    log(`ALARMA DE INTRUSIÓN: persona en la sala y nadie autorizado dentro (${out.reply.data.alarm_s} s de zumbador y LED rojo)`, "danger", describe(out.reply));
  } else {
    log(`Sensor interior: ${out.device.present ? "persona en la sala (sin alarma: hay alguien autorizado dentro o la puerta está en uso)" : "sala vacía"} a ${cm} cm`, "", describe(out.reply));
  }
}
$("approach").addEventListener("click", () => moveInside(10));
$("leave").addEventListener("click", () => moveInside(200));
$("online").addEventListener("change", async (e) => {
  const out = await act("/online", { online: e.target.checked });
  if (out) log(e.target.checked ? "ESP32 reconectado (latido enviado)" : "ESP32 desconectado: el backend lo marcará OFFLINE tras 45 s sin latido",
    e.target.checked ? "ok" : "danger");
});
$("sensor-ok").addEventListener("change", async (e) => {
  const out = await act("/sensors", { ultrasonic: e.target.checked ? "OK" : "TIMEOUT", rfid: "OK" });
  if (out) log(e.target.checked ? "HC-SR04 vuelve a responder" : "HC-SR04 sin respuesta (TIMEOUT) informado en el latido",
    e.target.checked ? "ok" : "danger", describe(out.reply));
});
$("heartbeat").addEventListener("click", async () => {
  const out = await act("/heartbeat");
  if (out) log("Latido enviado", "", describe(out.reply));
});

$("swipe").addEventListener("click", async () => {
  const uid = $("uid").value.trim() || $("card").value;
  if (!uid) { toast("Elige una tarjeta o escribe un UID", "error"); return; }
  stopPolling();
  setDecision("Validando…", "info");
  const out = await act("/card", { uid });
  if (!out) return;
  const r = out.reply;
  if (r.error) { log(r.error, "danger"); setDecision("Sin intento"); return; }
  const d = r.data ?? {};
  if (d.state === "DENIED") {
    setDecision(`DENEGADO: ${d.reason_code}`, "danger");
    log(`Tarjeta ${uid}: denegado en la validación inicial: ${reasonText(d.reason_code)}. La puerta no se abre.`, "danger", describe(r));
    return;
  }
  if (d.error) { log(describe(r), "danger"); setDecision("Error", "danger"); return; }
  log(`Tarjeta ${uid} leída → ${d.state}`, "", describe(r));
  $("face-hint").textContent = "El backend espera la verificación facial del titular (5 capturas). "
    + "En la salida también se exige el rostro, pero no una autorización vigente.";
  setDecision("Esperando rostro", "info");
  startPolling();
});

document.querySelectorAll("[data-face]").forEach((btn) => btn.addEventListener("click", async () => {
  const mode = btn.dataset.face;
  const out = await act("/face", { mode });
  const res = out?.reply?.data;
  if (!res) return;
  const label = { match: "rostro del titular", other: "rostro de otro ingeniero", stranger: "persona desconocida" }[mode];
  log(`Kiosco (${label}): ${res.state}${res.reason ? ` · ${res.reason}` : ""} · similitud ${res.score?.toFixed(2)} · ${res.matches}/${res.frames} capturas`,
    res.state === "FACE_OK" ? "ok" : res.state === "DENIED" ? "danger" : "");
}));

$("enroll-demo").addEventListener("click", async () => {
  const out = await guarded(() => api.post("/sim/enroll-demo-faces"));
  if (out) toast(`Rostros sintéticos registrados: ${out.enrolled.filter((x) => typeof x === "number").length}`, "ok");
});
// ------------------------------------------------------------------ entrada principal (QR)
async function entrancePoll({ quiet = false } = {}) {
  if (!code) return;
  const out = await act("/entrance-poll");
  if (!out) { stopEntranceAuto(); return; }
  const r = out.reply;
  if (r?.error) { log(`Entrada principal: ${r.error}`, "danger"); stopEntranceAuto(); return; }
  const sig = r?.data?.signal;
  if (!sig) {
    if (!quiet) log("Entrada principal: sin señal pendiente (LED apagado)", "", describe(r));
    return;
  }
  const name = sig.display_name ? ` · ${sig.display_name}` : "";
  if (sig.result === "GRANTED") {
    const ms = Number(sig.led_ms) || 5000;
    applyEntrance("GREEN", Date.now() + ms);
    log(`Entrada principal: señal GRANTED firmada → LED verde ${ms} ms${name}`, "ok", describe(r));
  } else if (sig.result === "DENIED") {
    applyEntrance("RED_BLINK", Date.now() + 3000);
    log(`Entrada principal: señal DENIED → LED rojo parpadea 3 veces y pitido${name}`, "danger", describe(r));
  } else {
    log(`Entrada principal: señal con resultado desconocido ignorada (fail-closed)`, "danger", describe(r));
  }
}

function stopEntranceAuto() {
  clearInterval(entranceAuto);
  entranceAuto = null;
  $("entrance-auto").checked = false;
}

$("entrance-poll").addEventListener("click", () => entrancePoll());
$("entrance-auto").addEventListener("change", (e) => {
  clearInterval(entranceAuto);
  entranceAuto = e.target.checked ? setInterval(() => entrancePoll({ quiet: true }), 1000) : null;
});

// ------------------------------------------------------------------ DHT11
function syncEnvLabels() {
  const fail = $("dht-fail").checked;
  $("temp-label").textContent = fail ? "sin lectura" : `${Number($("temp").value).toFixed(1)} °C`;
  $("hum-label").textContent = fail ? "sin lectura" : `${$("hum").value} %`;
  $("temp").disabled = fail;
  $("hum").disabled = fail;
}
["temp", "hum", "dht-fail"].forEach((id) => $(id).addEventListener("input", syncEnvLabels));
$("dht-fail").addEventListener("change", syncEnvLabels);

async function sendEnvironment() {
  const fail = $("dht-fail").checked;
  const body = fail
    ? { temperature_c: null, humidity_pct: null, sensor: "ERROR" }
    : { temperature_c: Math.round(Number($("temp").value) * 10) / 10,
        humidity_pct: Math.round(Number($("hum").value) * 10) / 10, sensor: "OK" };
  const out = await act("/environment", body);
  if (!out) return;
  const r = out.reply;
  if (r?.error) { log(`DHT11: ${r.error}`, "danger"); return; }
  const d = r?.data ?? {};
  if (d.error) { log(`DHT11: ${describe(r)}`, "danger"); return; }
  const what = fail ? "sensor con fallo (ERROR)" : `${body.temperature_c} °C · ${body.humidity_pct} %`;
  log(`DHT11: lectura ${what} → ventilador ${d.fan ? "ENCENDIDO" : "apagado"}, alarma ${d.alarm ? "ACTIVA" : "inactiva"}`,
    d.alarm ? "danger" : d.fan ? "" : "ok", describe(r));
  // Refleja la respuesta firmada aunque el estado del simulador aún no la incluya.
  renderEnvironment({ fan: Boolean(d.fan), env_alarm: Boolean(d.alarm), ...(out.device ?? {}) });
}
$("env-send").addEventListener("click", sendEnvironment);
$("env-hot").addEventListener("click", () => { $("dht-fail").checked = false; $("temp").value = 30; syncEnvLabels(); sendEnvironment(); });
$("env-critical").addEventListener("click", () => { $("dht-fail").checked = false; $("temp").value = 35; syncEnvLabels(); sendEnvironment(); });
syncEnvLabels();

$("clear").addEventListener("click", () => { $("log").innerHTML = ""; });

await loadState();
setInterval(() => { if (!pollTimer) loadState(); }, 5000);
