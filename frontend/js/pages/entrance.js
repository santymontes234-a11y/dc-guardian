// Entrada principal — acceso con credencial QR (contrato QR + DHT11 §2).
// La webcam se lee en el navegador con jsQR (vendorizado, global `jsQR`). Al detectar un texto
// `DCG-QR1:…` se envía a POST /kiosk/entrance/scan con la autenticación de kiosco. El backend
// decide (Registro 2) y encola la señal para el LED verde del ESP32; aquí solo se muestra.
// Fail-closed: cualquier error o respuesta inesperada se presenta como acceso denegado.
import { ApiError } from "/js/api.js";
import { startClock } from "/js/brand.js";
import { CameraError, isActive, listCameras, startCamera } from "/js/camera.js";
import { kioskApi, kioskToken, setKioskToken } from "/js/kiosk-auth.js";
import { reasonText } from "/js/ui.js";
import { connectEvents } from "/js/ws.js";

const $ = (id) => document.getElementById(id);
const PREFIX = "DCG-QR1:";
const DEBOUNCE_MS = 5000;   // mismo QR ignorado durante 5 s
const RESULT_MS = 6000;     // tiempo que se muestra el resultado
const LED_MS = 5000;        // led_ms por defecto del contrato
const SCAN_EVERY_MS = 150;

// Textos propios de la entrada (los genéricos hablan de "tarjeta").
const ENTRANCE_REASON = {
  NO_VALID_AUTH: "No tiene una autorización aprobada para la entrada principal",
  REQUEST_PENDING: "Su solicitud de autorización aún no ha sido aprobada",
  AUTH_NOT_STARTED: "Su autorización todavía no ha comenzado",
  AUTH_EXPIRED: "Su autorización ha vencido",
};
const why = (r) => (r?.reason_code && (ENTRANCE_REASON[r.reason_code] ?? reasonText(r.reason_code))) || r?.reason
  || "Credencial no válida";

const params = new URLSearchParams(location.search);
const device = (params.get("device") || "DC-DOOR-01").toUpperCase();

let busy = false;
let last = { text: null, at: 0 };
let resetTimer = null;
let ledTimer = null;
let hintAt = 0;

startClock($("clock"));

// ------------------------------------------------------------------ presentación
function setResult(state, title, detail = "") {
  $("result").dataset.state = state;
  $("result-title").textContent = title;
  $("result-detail").textContent = detail;
  $("stage").classList.remove("ok", "denied", "awaiting");
  if (state === "granted") $("stage").classList.add("ok");
  else if (state === "denied") $("stage").classList.add("denied");
  else if (state === "busy") $("stage").classList.add("awaiting");
  clearTimeout(resetTimer);
  if (state === "granted" || state === "denied" || state === "warn") {
    resetTimer = setTimeout(idle, RESULT_MS);
  }
}

function idle() {
  setResult("idle", "Esperando código QR", "La puerta permanece cerrada hasta validar la credencial.");
  $("msg").textContent = "Muestre su código QR a la cámara";
  $("sub").textContent = "Coloque la credencial dentro del recuadro, a unos 20 cm";
}

function greenLed(ms) {
  clearTimeout(ledTimer);
  redLed(false);
  $("led-green").classList.add("on");
  $("led-green-state").textContent = "Encendido · puerta abierta";
  ledTimer = setTimeout(() => {
    $("led-green").classList.remove("on");
    $("led-green-state").textContent = "Apagado";
  }, ms);
}

function redLed(blink) {
  const led = $("led-red");
  led.classList.remove("blink");
  $("led-red-state").textContent = "Apagado";
  if (!blink) return;
  clearTimeout(ledTimer);
  $("led-green").classList.remove("on");
  $("led-green-state").textContent = "Apagado";
  void led.offsetWidth; // reinicia la animación
  led.classList.add("blink");
  $("led-red-state").textContent = "Parpadeando";
  setTimeout(() => { led.classList.remove("blink"); $("led-red-state").textContent = "Apagado"; }, 3000);
}

function denied(detail) {
  setResult("denied", "ACCESO DENEGADO", detail);
  $("msg").textContent = "Acceso denegado";
  $("sub").textContent = detail;
  redLed(true);
}

// ------------------------------------------------------------------ validación
async function submit(qrText, source) {
  const text = String(qrText ?? "").trim();
  if (!text || busy) return;
  const now = Date.now();
  if (source === "camera" && text === last.text && now - last.at < DEBOUNCE_MS) return;
  last = { text, at: now };
  busy = true;
  setResult("busy", "Validando credencial…", "Consultando autorización vigente");
  try {
    const r = await kioskApi.post("/kiosk/entrance/scan", { qr_text: text });
    if (r?.result === "GRANTED") {
      const who = [r.display_name, r.position].filter(Boolean).join(", ");
      setResult("granted", "ACCESO PERMITIDO", who || "Credencial válida");
      $("msg").textContent = r.display_name ? `Bienvenido/a, ${r.display_name}` : "Acceso permitido";
      $("sub").textContent = "Puede pasar: la puerta de la entrada principal está abierta";
      greenLed(LED_MS);
    } else {
      // DENIED o cualquier valor inesperado: puerta cerrada.
      denied(why(r));
    }
  } catch (err) {
    if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
      setResult("warn", "Kiosco sin autorización", "Configure el token de kiosco para validar credenciales.");
      $("token-dialog").showModal();
    } else if (err instanceof ApiError && err.status === 429) {
      denied(reasonText("RATE_LIMITED"));
    } else if (err instanceof ApiError && err.status === 0) {
      denied("Sin conexión con el servidor: la puerta permanece cerrada");
    } else {
      denied(err?.message ? `Error del servidor: ${err.message}` : "Error inesperado: la puerta permanece cerrada");
    }
  } finally {
    busy = false;
  }
}

$("manual").addEventListener("submit", (e) => {
  e.preventDefault();
  const value = $("manual-text").value;
  if (!value.trim()) { $("manual-text").focus(); return; }
  submit(value, "manual");
  $("manual-text").value = ""; // no dejar la credencial a la vista
});

// ------------------------------------------------------------------ lector QR
const scanCanvas = document.createElement("canvas");
const scanCtx = scanCanvas.getContext("2d", { willReadFrequently: true });

function flashGuide() {
  $("guide").classList.remove("hit");
  void $("guide").offsetWidth;
  $("guide").classList.add("hit");
}

function scanOnce() {
  const video = $("video");
  if (typeof window.jsQR !== "function" || !isActive(video) || !video.videoWidth || document.hidden) return;
  const scale = Math.min(1, 640 / Math.max(video.videoWidth, video.videoHeight));
  const w = Math.round(video.videoWidth * scale);
  const h = Math.round(video.videoHeight * scale);
  if (scanCanvas.width !== w) scanCanvas.width = w;
  if (scanCanvas.height !== h) scanCanvas.height = h;
  scanCtx.drawImage(video, 0, 0, w, h);
  const code = window.jsQR(scanCtx.getImageData(0, 0, w, h).data, w, h, { inversionAttempts: "dontInvert" });
  if (!code?.data) return;
  flashGuide();
  if (code.data.startsWith(PREFIX)) {
    submit(code.data, "camera");
  } else if (!busy && Date.now() - hintAt > 3000) {
    // Otros QR (URL, etc.) no se envían al servidor: no son credenciales.
    hintAt = Date.now();
    $("sub").textContent = "Este código QR no es una credencial de Telecom Conecta";
  }
}

function loop() {
  try { scanOnce(); } catch { /* fotograma no disponible */ }
  setTimeout(loop, SCAN_EVERY_MS);
}

async function initCamera() {
  try {
    await startCamera($("video"), { deviceId: $("camera").value || undefined });
    const cams = await listCameras();
    if (!$("camera").options.length) {
      cams.forEach((c, i) => $("camera").add(new Option(c.label || `Cámara ${i + 1}`, c.deviceId)));
    }
    $("start-cam").textContent = "Cámara activa";
    idle();
  } catch (e) {
    $("msg").textContent = "Cámara no disponible";
    $("sub").textContent = `${e instanceof CameraError ? e.message : String(e)} Use la entrada manual.`;
  }
}
$("start-cam").addEventListener("click", initCamera);
$("camera").addEventListener("change", initCamera);

// ------------------------------------------------------------------ autenticación
$("token-form").addEventListener("submit", () => {
  setKioskToken($("token").value);
  location.reload();
});

async function ensureAuth() {
  try {
    const p = await kioskApi.get("/kiosk/pending", { device_code: device });
    $("device-name").textContent = `${p.device.name} (${p.device.device_code})`;
    return true;
  } catch (e) {
    if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
      $("token-dialog").showModal();
      return false;
    }
    // Dispositivo inexistente u otro fallo: se puede seguir; el backend decidirá en cada escaneo.
    $("device-name").textContent = e instanceof ApiError && e.status === 404 ? `Dispositivo ${device} no registrado` : "";
    return true;
  }
}

if (typeof window.jsQR !== "function") {
  $("sub").textContent = "Lector QR no disponible: use la entrada manual";
}

if (await ensureAuth()) {
  const events = connectEvents({ kioskToken: kioskToken() });
  events.on("status", (s) => {
    $("live").className = `badge badge-${s === "open" ? "ok" : "danger"}`;
    $("live").textContent = s === "open" ? "En línea" : "Sin conexión";
  });
  await initCamera();
  loop();
}
