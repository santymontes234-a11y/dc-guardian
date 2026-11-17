import { ready } from "/js/layout.js";
import { api, ApiError, escapeHtml, fmtDate, guarded } from "/js/api.js";
import { connectEvents } from "/js/ws.js";
import { $, ALERT_HEAD, SESSION_HEAD, alertRow, badge, emptyRow, methodText, reasonText, sessionRow, zoneText } from "/js/ui.js";
import { startClock } from "/js/brand.js";
import { LOG_COLS, LOG_HEAD, fetchAccessLog, logRow } from "/js/access-log.js";
import { lineChart } from "/js/env-chart.js";

await ready;
startClock($("today"));
$("log-head").innerHTML = LOG_HEAD;

$("sess-head").innerHTML = SESSION_HEAD;
$("deny-head").innerHTML = SESSION_HEAD;
$("alert-head").innerHTML = ALERT_HEAD;

const EVENT_TEXT = {
  "access.card_read": "Tarjeta leída",
  "access.awaiting_face": "Esperando verificación facial",
  "access.face_retry": "Rostro no detectado, reintento",
  "access.face_ok": "Rostro verificado",
  "access.granted": "Acceso concedido: se ordena abrir",
  "access.opened": "Puerta abierta",
  "access.closed": "Puerta cerrada",
  "access.exit_requested": "Salida solicitada",
  "access.denied": "Acceso denegado",
  "access.timeout": "Tiempo de verificación agotado",
  "alert.created": "Alerta",
  "alert.acknowledged": "Alerta atendida",
  "device.status": "Estado de dispositivo",
  "device.presence": "Presencia",
  "request.updated": "Solicitud actualizada",
  "entrance.scan": "Entrada principal (QR)",
  "access.qr": "Entrada principal (QR)",
  "qr.scan": "Entrada principal (QR)",
};

function kpi(label, value, tone = "") {
  return `<div class="card kpi"><span class="value ${tone}">${value}</span><span class="label">${label}</span></div>`;
}

function renderDevices(devices) {
  $("devices").innerHTML = devices.length ? devices.map((d) => {
    const hw = d.hw ?? {};
    const sensors = hw.sensors ?? {};
    return `<div class="device">
      <div class="row"><b>${escapeHtml(d.device_code)}</b> ${badge(d.status)}
        <span class="muted">${escapeHtml(d.name)}</span></div>
      <div class="meta">
        <div><span>Último latido</span><br><b>${fmtDate(d.last_seen_at)}</b></div>
        <div><span>Puerta</span><br><b>${escapeHtml(hw.door ?? "—")}</b></div>
        <div><span>Distancia</span><br><b>${hw.distance_cm == null || hw.distance_cm < 0 ? "sin lectura" : `${hw.distance_cm} cm`}</b>
          <span>(umbral ${d.presence_threshold_cm} cm)</span></div>
        <div><span>RC522</span><br>${badge(sensors.rfid ?? "—")}</div>
        <div><span>HC-SR04</span><br>${badge(sensors.ultrasonic ?? "—", sensors.ultrasonic && sensors.ultrasonic !== "OK" ? "danger" : undefined)}</div>
        <div><span>DHT11</span><br>${badge(sensors.dht ?? "—", sensors.dht && sensors.dht !== "OK" ? "danger" : undefined)}</div>
        <div><span>Firmware · RSSI</span><br><b>${escapeHtml(d.firmware_version ?? "—")} · ${hw.rssi ?? "—"} dBm</b></div>
      </div></div>`;
  }).join("") : '<p class="empty">No hay dispositivos registrados.</p>';
}

async function load() {
  const d = await guarded(() => api.get("/stats/dashboard"));
  if (!d) return;
  const req = d.requests.by_status;
  const online = d.devices.filter((x) => x.status === "ONLINE").length;
  $("kpis").innerHTML = [
    kpi("Ingenieros activos", `${d.engineers.by_status.ACTIVO ?? 0}<small class="muted"> / ${d.engineers.total}</small>`),
    kpi("Solicitudes pendientes", req.PENDIENTE ?? 0, (req.PENDIENTE ?? 0) ? "warn" : ""),
    kpi("Autorizaciones vigentes", d.requests.in_force, "ok"),
    kpi("Accesos (24 h)", d.access.entries_24h),
    kpi("Salidas (24 h)", d.access.exits_24h),
    kpi("Denegaciones (24 h)", d.access.denied_24h, d.access.denied_24h ? "danger" : ""),
    kpi("Alertas abiertas", d.alerts.open_total, d.alerts.open_by_severity.CRITICAL ? "danger" : d.alerts.open_total ? "warn" : ""),
    kpi("Dispositivos en línea", `${online} / ${d.devices.length}`, online < d.devices.length ? "danger" : "ok"),
  ].join("");
  renderDevices(d.devices);
  $("inside").innerHTML = d.engineers.inside.length
    ? `<ul>${d.engineers.inside.map((e) => `<li>${escapeHtml(e.full_name)} <span class="mono muted">${escapeHtml(e.engineer_id)}</span>
        · desde ${fmtDate(e.since)}</li>`).join("")}</ul>`
    : '<p class="muted" style="margin:0">Nadie dentro.</p>';
  const max = Math.max(1, ...d.denials_by_reason.map((r) => r.count));
  $("reasons").innerHTML = d.denials_by_reason.length ? d.denials_by_reason.map((r) =>
    `<div class="reason-bar"><span>${escapeHtml(r.reason ?? r.reason_code)}</span><b>${r.count}</b>
      <span class="bar" style="width:${(100 * r.count) / max}%"></span></div>`).join("")
    : '<p class="muted" style="margin:0">Sin denegaciones.</p>';
  $("sessions").innerHTML = d.recent_sessions.map(sessionRow).join("") || emptyRow(7, "Sin accesos todavía");
  $("denials").innerHTML = d.recent_denials.map(sessionRow).join("") || emptyRow(7, "Sin denegaciones");
  const open = d.alerts.latest.filter((a) => !a.acknowledged_at);
  $("alerts").innerHTML = open.map((a) => alertRow(a)).join("") || emptyRow(5, "Sin alertas abiertas");
  loadLog();
}

async function loadLog() {
  const page = await guarded(() => fetchAccessLog({ limit: 10 }));
  if (!page) return;
  $("log-rows").innerHTML = page.items.map(logRow).join("") || emptyRow(LOG_COLS, "Sin registros todavía");
}

// ------------------------------------------------------------------ DHT11 (sala de servidores)
const ENV_MINUTES = 60;
const STALE_MS = 35_000; // el firmware envía cada 10 s
const DEFAULT_TH = { temp_high_c: 27, temp_critical_c: 32, humidity_low_pct: 20, humidity_high_pct: 80 };
let env = null;
let series = [];

const num = (v) => (v === null || v === undefined || v === "" || !Number.isFinite(Number(v)) ? null : Number(v));
const thresholds = () => ({ ...DEFAULT_TH, ...(env?.thresholds ?? {}) });

function setMetric(id, text, tone = "") {
  $(id).textContent = text;
  $(id).className = `value${$(id).classList.contains("small") ? " small" : ""}${tone ? ` ${tone}` : ""}`;
}

function renderEnv() {
  const th = thresholds();
  if (!env?.at) {
    $("env-fresh").className = "badge badge-muted";
    $("env-fresh").textContent = "Sin lecturas";
  } else {
    const t = num(env.temperature_c);
    const h = num(env.humidity_pct);
    const sensorOk = env.sensor === "OK";
    const at = env.at ? Date.parse(env.at) : NaN;
    const stale = !Number.isFinite(at) || Date.now() - at > STALE_MS;
    $("env-fresh").className = `badge badge-${stale ? "warn" : "ok"}`;
    $("env-fresh").textContent = stale ? "Sin lecturas recientes" : "En vivo";
    const tTone = t === null ? "" : t >= th.temp_critical_c ? "danger" : t >= th.temp_high_c ? "warn" : "ok";
    setMetric("env-temp", t === null ? "—" : `${t.toFixed(1)} °C`, tTone);
    $("env-temp-hint").textContent = t === null ? "" : t >= th.temp_critical_c ? "Crítica"
      : t >= th.temp_high_c ? "Alta: se enciende el ventilador" : "Normal";
    const hOut = h !== null && (h < th.humidity_low_pct || h > th.humidity_high_pct);
    setMetric("env-hum", h === null ? "—" : `${h.toFixed(1)} %`, h === null ? "" : hOut ? "warn" : "ok");
    $("env-hum-hint").textContent = h === null ? "" : hOut ? "Fuera de rango" : `Rango ${th.humidity_low_pct}–${th.humidity_high_pct} %`;
    const fan = Boolean(env.fan);
    $("env-fan").textContent = fan ? "Encendido" : "Apagado";
    $("env-fan-icon").classList.toggle("on", fan);
    const alarm = Boolean(env.alarm);
    setMetric("env-alarm", alarm ? "ACTIVA" : "Normal", alarm ? "danger" : "ok");
    setMetric("env-sensor", sensorOk ? "DHT11 OK" : "DHT11 con fallo", sensorOk ? "ok" : "danger");
    $("env-at").textContent = env.at ? `${devicePrefix(env.device_code)}${fmtDate(env.at)}` : "";
  }
  const pts = (key) => series.map((p) => ({ t: p.t, v: p[key] }));
  lineChart($("chart-temp"), { points: pts("temp"), minutes: ENV_MINUTES, unit: " °C", domain: [15, 35], label: "Temperatura",
    thresholds: [{ value: th.temp_high_c, label: "Alta", tone: "warn" }, { value: th.temp_critical_c, label: "Crítica", tone: "danger" }] });
  lineChart($("chart-hum"), { points: pts("hum"), minutes: ENV_MINUTES, unit: " %", domain: [0, 100], label: "Humedad",
    thresholds: [{ value: th.humidity_low_pct, label: "Mín.", tone: "warn" }, { value: th.humidity_high_pct, label: "Máx.", tone: "warn" }] });
}

const devicePrefix = (code) => (code ? `${code} · ` : "");

function pushPoint(r) {
  const t = Date.parse(r.at);
  if (!Number.isFinite(t)) return;
  const ok = r.sensor === undefined || r.sensor === "OK";
  series.push({ t, temp: ok ? num(r.temperature_c) : null, hum: ok ? num(r.humidity_pct) : null });
  series.sort((a, b) => a.t - b.t);
  const cut = Date.now() - ENV_MINUTES * 60_000;
  series = series.filter((p) => p.t >= cut);
}

async function loadEnv() {
  try {
    env = await api.get("/monitoring/environment/latest");
  } catch (err) {
    if (!(err instanceof ApiError) || err.status !== 404) console.warn("DHT11:", err.message);
  }
  try {
    const h = await api.get("/monitoring/environment", { minutes: ENV_MINUTES });
    series = [];
    for (const r of h.items ?? []) pushPoint(r);
  } catch (err) {
    if (!(err instanceof ApiError) || err.status !== 404) console.warn("DHT11 historial:", err.message);
  }
  renderEnv();
}

function onEnvironment(evt) {
  const data = evt.data ?? {};
  const at = data.at ?? evt.ts;
  env = { ...(env ?? {}), ...data, at, thresholds: data.thresholds ?? env?.thresholds };
  pushPoint({ ...data, at });
  renderEnv();
}

let count = 0;
function addFeed(evt) {
  const feed = $("feed");
  if (count === 0) feed.innerHTML = "";
  count += 1;
  $("evt-count").textContent = `${count} eventos`;
  const data = evt.data ?? {};
  let text = "";
  if (data.method === "QR" || data.area === "ENTRADA_PRINCIPAL" || data.zone === "ENTRADA_PRINCIPAL"
      || data.zone?.code === "ENTRADA_PRINCIPAL") {
    const who = data.display_name ?? data.person ?? data.engineer?.full_name ?? "Credencial QR";
    const res = data.result?.value ?? data.result;
    text = `${who} · ${zoneText("ENTRADA_PRINCIPAL")} · ${methodText("QR")} · ${res === "GRANTED" ? "permitido" : "denegado"}`
      + `${data.reason_code ? ` · ${reasonText(data.reason_code)}` : ""}`;
  } else if (evt.type.startsWith("access.")) {
    const who = data.engineer ? `${data.engineer.full_name} (${data.engineer.engineer_id})` : `tarjeta ${data.card_uid ?? "?"}`;
    text = `${who} · ${data.device_code ?? ""}${data.reason ? ` · ${data.reason}` : ""}`;
  } else if (evt.type.startsWith("alert.")) {
    text = `[${data.severity}] ${data.message ?? data.type}`;
  } else if (evt.type === "device.status") {
    text = `${data.device_code}: ${data.status}${data.hw?.sensors?.ultrasonic && data.hw.sensors.ultrasonic !== "OK" ? " · HC-SR04 sin respuesta" : ""}`;
  } else if (evt.type === "device.presence") {
    text = `${data.device_code}: ${data.present ? "persona presente" : "sin presencia"} (${data.distance_cm} cm)`;
  } else {
    text = JSON.stringify(data).slice(0, 120);
  }
  const qrResult = data.result?.value ?? data.result;
  const tone = evt.type === "access.denied" || data.severity === "CRITICAL" || qrResult === "DENIED" ? "danger"
    : evt.type === "access.granted" || qrResult === "GRANTED" ? "ok" : undefined;
  const li = document.createElement("li");
  li.className = "new";
  li.innerHTML = `<time>${new Date(evt.ts).toLocaleTimeString("es")}</time>
    <span class="type">${badge(EVENT_TEXT[evt.type] ?? evt.type, tone)}</span><span>${escapeHtml(text)}</span>`;
  feed.prepend(li);
  while (feed.children.length > 100) feed.lastChild.remove();
}

let reloadTimer = null;
function scheduleReload() {
  clearTimeout(reloadTimer);
  reloadTimer = setTimeout(load, 400); // agrupa ráfagas de eventos
}

const events = connectEvents();
events.on("status", (s) => {
  $("live").className = `badge badge-${s === "open" ? "ok" : "danger"}`;
  $("live").textContent = s === "open" ? "En vivo" : "Sin conexión en tiempo real";
});
events.on("environment", onEnvironment);
events.on("*", (evt) => {
  if (!evt?.type || evt.type === "hello") return; // "status" llega como texto, no como evento
  if (evt.type === "environment") return; // cada 10 s: tarjeta propia, no inunda el registro
  addFeed(evt);
  scheduleReload();
});

await Promise.all([load(), loadEnv()]);
setInterval(load, 30000); // por si se pierde algún evento
setInterval(loadEnv, 60000);
setInterval(renderEnv, 10000); // marca "sin lecturas recientes" y desplaza la gráfica
