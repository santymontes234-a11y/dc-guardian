import { ready } from "/js/layout.js";
import { api, escapeHtml, fmtDate, guarded } from "/js/api.js";
import { connectEvents } from "/js/ws.js";
import { $, ALERT_HEAD, SESSION_HEAD, alertRow, badge, emptyRow, sessionRow } from "/js/ui.js";

await ready;

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
}

let count = 0;
function addFeed(evt) {
  const feed = $("feed");
  if (count === 0) feed.innerHTML = "";
  count += 1;
  $("evt-count").textContent = `${count} eventos`;
  const data = evt.data ?? {};
  let text = "";
  if (evt.type.startsWith("access.")) {
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
  const tone = evt.type === "access.denied" || data.severity === "CRITICAL" ? "danger"
    : evt.type === "access.granted" ? "ok" : undefined;
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
events.on("*", (evt) => {
  if (!evt?.type || evt.type === "hello") return; // "status" llega como texto, no como evento
  addFeed(evt);
  scheduleReload();
});

await load();
setInterval(load, 30000); // por si se pierde algún evento
