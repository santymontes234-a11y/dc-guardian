// Cámara del navegador (getUserMedia). Compartido por el registro de ingenieros y el kiosco.
//   import { startCamera, stopCamera, captureJpeg, listCameras } from "/js/camera.js";
//   const stream = await startCamera(videoEl);          // lanza CameraError con mensaje en español
//   const blob = await captureJpeg(videoEl);           // JPEG sin espejo, a la resolución del vídeo
//   stopCamera(videoEl);
// Las imágenes nunca se guardan en el navegador: solo viven en memoria hasta enviarse.

export class CameraError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "CameraError";
    this.code = code;
  }
}

const MESSAGES = {
  NotAllowedError: "Permiso de cámara denegado. Habilítalo en el navegador para continuar.",
  NotFoundError: "No se encontró ninguna cámara conectada.",
  NotReadableError: "La cámara está en uso por otra aplicación.",
  OverconstrainedError: "La cámara no admite la resolución solicitada.",
  SecurityError: "La cámara solo funciona en HTTPS o en localhost.",
};

export async function listCameras() {
  if (!navigator.mediaDevices?.enumerateDevices) return [];
  const devices = await navigator.mediaDevices.enumerateDevices();
  return devices.filter((d) => d.kind === "videoinput");
}

/** Abre la cámara y la muestra en `videoEl`. Devuelve el MediaStream. */
export async function startCamera(videoEl, { deviceId, width = 1280, height = 720 } = {}) {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new CameraError("UNSUPPORTED", "Este navegador no permite usar la cámara (requiere HTTPS o localhost).");
  }
  stopCamera(videoEl);
  const video = { width: { ideal: width }, height: { ideal: height }, facingMode: "user" };
  if (deviceId) video.deviceId = { exact: deviceId };
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video, audio: false });
  } catch (err) {
    throw new CameraError(err.name ?? "CAMERA_ERROR", MESSAGES[err.name] ?? `No se pudo abrir la cámara (${err.message}).`);
  }
  videoEl.srcObject = stream;
  videoEl.muted = true;
  videoEl.playsInline = true;
  await videoEl.play();
  if (!videoEl.videoWidth) {
    await new Promise((resolve) => videoEl.addEventListener("loadedmetadata", resolve, { once: true }));
  }
  return stream;
}

export function stopCamera(videoEl) {
  const stream = videoEl?.srcObject;
  if (stream) stream.getTracks().forEach((t) => t.stop());
  if (videoEl) videoEl.srcObject = null;
}

export function isActive(videoEl) {
  return Boolean(videoEl?.srcObject?.getVideoTracks().some((t) => t.readyState === "live"));
}

/** Fotograma actual como JPEG (sin espejo). `maxSide` limita el tamaño enviado al servidor. */
export function captureJpeg(videoEl, { quality = 0.92, maxSide = 1280 } = {}) {
  const w = videoEl.videoWidth;
  const h = videoEl.videoHeight;
  if (!w || !h) return Promise.reject(new CameraError("NOT_READY", "La cámara todavía no está lista."));
  const scale = Math.min(1, maxSide / Math.max(w, h));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(w * scale);
  canvas.height = Math.round(h * scale);
  canvas.getContext("2d").drawImage(videoEl, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new CameraError("CAPTURE", "No se pudo capturar la imagen."))),
      "image/jpeg", quality));
}

/** Igual que captureJpeg pero en base64 (sin prefijo data:), por si una API lo requiere. */
export async function captureBase64(videoEl, opts) {
  const blob = await captureJpeg(videoEl, opts);
  const buf = new Uint8Array(await blob.arrayBuffer());
  let bin = "";
  for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode(...buf.subarray(i, i + 0x8000));
  return btoa(bin);
}
