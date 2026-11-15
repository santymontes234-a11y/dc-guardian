import { ready } from "/js/layout.js";
import { api, escapeHtml, guarded, toast } from "/js/api.js";
import { $, reasonText } from "/js/ui.js";

await ready;

let code = null;
let dev = null;
let pollTimer = null;
let closeTimer = null;

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
}

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
}

$("device").addEventListener("change", (e) => { code = e.target.value; stopPolling(); loadState(); });

let distTimer = null;
$("distance").addEventListener("input", (e) => {
  $("dist-label").textContent = `${e.target.value} cm`;
  clearTimeout(distTimer);
  distTimer = setTimeout(async () => {
    const out = await act("/distance", { distance_cm: Number(e.target.value) });
    if (out?.reply?.data) log(`Presencia ${out.device.present ? "detectada" : "perdida"} a ${e.target.value} cm`, "", describe(out.reply));
  }, 250);
});
$("approach").addEventListener("click", async () => {
  const out = await act("/distance", { distance_cm: 30 });
  if (out) log("La persona se acerca a 30 cm: presencia detectada", "", describe(out.reply));
});
$("leave").addEventListener("click", async () => {
  const out = await act("/distance", { distance_cm: 200 });
  if (out) log("La persona se aleja a 200 cm", "", describe(out.reply));
});
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
$("clear").addEventListener("click", () => { $("log").innerHTML = ""; });

await loadState();
setInterval(() => { if (!pollTimer) loadState(); }, 5000);
