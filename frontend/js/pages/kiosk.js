// Kiosco junto a la puerta (pasos 11–13): cuando el ESP32 lee una tarjeta autorizada, el backend
// avisa por WebSocket; el kiosco toma N capturas distintas (~200 ms entre ellas) y las envía a
// POST /vision/verify. Autenticación: sesión de administrador o token de kiosco.
import { startClock } from "/js/brand.js";
import { CameraError, captureJpeg, isActive, listCameras, startCamera } from "/js/camera.js";
import { reasonText } from "/js/ui.js";
import { connectEvents } from "/js/ws.js";

const $ = (id) => document.getElementById(id);
startClock($("clock"));
const params = new URLSearchParams(location.search);
const device = (params.get("device") || "DC-DOOR-01").toUpperCase();
const KEY = "dcg-kiosk-token";
let token = params.get("token") || safeGet(KEY);
if (params.has("token")) {
  // No dejar el token en la barra de direcciones ni en el historial.
  if (token) safeSet(KEY, token);
  history.replaceState(null, "", `${location.pathname}?device=${encodeURIComponent(device)}`);
}
let frames = 5;
let busy = false;
let current = null; // session id being verified

function safeGet(k) { try { return sessionStorage.getItem(k); } catch { return null; } }
function safeSet(k, v) { try { sessionStorage.setItem(k, v); } catch { /* sin almacenamiento */ } }

function show(msg, sub = "", tone = "") {
  $("msg").textContent = msg;
  $("sub").textContent = sub;
  $("overlay").parentElement.className = `stage ${tone}`;
}

async function call(method, path, body) {
  const headers = { Accept: "application/json" };
  if (token) headers["X-Kiosk-Token"] = token;
  const res = await fetch(`/api/v1${path}`, { method, headers, body, credentials: "same-origin" });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = new Error(data?.error?.message ?? res.statusText);
    err.status = res.status;
    throw err;
  }
  return data;
}

async function ensureAuth() {
  try {
    const p = await call("GET", `/kiosk/pending?device_code=${encodeURIComponent(device)}`);
    frames = p.frames ?? 5;
    $("device-name").textContent = `${p.device.name} (${p.device.device_code})`;
    return p;
  } catch (e) {
    if (e.status === 401 || e.status === 403) {
      $("token-dialog").showModal();
      return null;
    }
    show("Error", e.message, "denied");
    return null;
  }
}

$("token-form").addEventListener("submit", () => {
  token = $("token").value.trim();
  safeSet(KEY, token);
  location.reload();
});

async function initCamera() {
  try {
    await startCamera($("video"), { deviceId: $("camera").value || undefined });
    const cams = await listCameras();
    if (!$("camera").options.length) {
      // new Option() escapa el texto: el nombre de la cámara lo controla el dispositivo USB.
      cams.forEach((c, i) => $("camera").add(new Option(c.label || `Cámara ${i + 1}`, c.deviceId)));
    }
    $("start-cam").textContent = "Cámara activa";
  } catch (e) {
    show("Cámara no disponible", e instanceof CameraError ? e.message : String(e), "denied");
  }
}
$("start-cam").addEventListener("click", initCamera);
$("camera").addEventListener("change", initCamera);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function verify(session) {
  if (busy || current === session.id) return;
  busy = true;
  current = session.id;
  const name = session.engineer?.full_name ?? "titular de la tarjeta";
  try {
    if (!isActive($("video"))) await initCamera();
    show(`${name}, mire a la cámara`, "Tomando capturas…", "awaiting");
    await sleep(600);
    const form = new FormData();
    form.append("session_id", session.id);
    for (let i = 0; i < frames; i += 1) {
      form.append("frames", await captureJpeg($("video"), { quality: 0.9, maxSide: 960 }), `f${i}.jpg`);
      $("sub").textContent = `Captura ${i + 1} de ${frames}`;
      await sleep(220); // variación natural entre capturas (prueba de vida básica)
    }
    $("sub").textContent = "Verificando…";
    const r = await call("POST", "/vision/verify", form);
    if (r.state === "FACE_OK") {
      show("Identidad verificada", "Espere a que se abra la puerta", "ok");
    } else if (r.retry) {
      show("No se detectó bien el rostro", `${reasonText(r.face_reason_code)}. Reintentando…`, "awaiting");
      current = null;
      busy = false;
      await sleep(800);
      return verify(session);
    } else {
      show("Acceso denegado", reasonText(r.reason_code) || r.state, "denied");
    }
  } catch (e) {
    show("No se pudo verificar", e.message, "denied");
  } finally {
    busy = false;
  }
}

function onAccess(evt) {
  const s = evt.data;
  if (!s || s.device_code !== device) return;
  if (evt.type === "access.awaiting_face") verify(s);
  else if (evt.type === "access.granted") show("Acceso concedido", s.direction === "SALIDA" ? "Salida registrada" : "Puede pasar", "ok");
  else if (evt.type === "access.denied") show("Acceso denegado", s.reason ?? "", "denied");
  else if (evt.type === "access.timeout") show("Tiempo agotado", "Vuelva a pasar la tarjeta", "denied");
  else if (evt.type === "access.closed") setTimeout(() => show("Acérquese a la puerta y pase su tarjeta"), 2500);
}

const pending = await ensureAuth();
if (pending) {
  await initCamera();
  const events = connectEvents({ kioskToken: token });
  events.on("status", (s) => {
    $("live").className = `badge badge-${s === "open" ? "ok" : "danger"}`;
    $("live").textContent = s === "open" ? "En línea" : "Sin conexión";
  });
  events.on("access.*", onAccess);
  if (pending.session) verify(pending.session);
  // Respaldo por si se pierde un evento: consulta la sesión pendiente cada 2 s.
  setInterval(async () => {
    if (busy) return;
    try {
      const p = await call("GET", `/kiosk/pending?device_code=${encodeURIComponent(device)}`);
      if (p.session && p.session.id !== current) verify(p.session);
    } catch { /* sin conexión: el indicador ya lo muestra */ }
  }, 2000);
}
