// Piezas de presentación compartidas por dashboard, accesos, alertas y auditoría.
import { escapeHtml, fmtDate } from "/js/api.js";

export const $ = (id) => document.getElementById(id);

const STATE_TONE = {
  GRANTED: "ok", OPENED: "ok", CLOSED: "ok", FACE_OK: "info", AWAITING_FACE: "info", CARD_READ: "info",
  DENIED: "danger", TIMEOUT: "warn",
  ONLINE: "ok", OFFLINE: "danger", DESHABILITADO: "muted",
  INFO: "info", WARN: "warn", CRITICAL: "danger",
  OK: "ok", TIMEOUT_SENSOR: "danger", ERROR: "danger",
};

const STATE_LABEL = {
  GRANTED: "Concedido", OPENED: "Puerta abierta", CLOSED: "Completado", FACE_OK: "Rostro verificado",
  AWAITING_FACE: "Esperando rostro", CARD_READ: "Tarjeta leída", DENIED: "Denegado", TIMEOUT: "Tiempo agotado",
};

export function badge(value, tone) {
  const t = tone ?? STATE_TONE[value] ?? "muted";
  return `<span class="badge badge-${t}">${escapeHtml(STATE_LABEL[value] ?? value ?? "—")}</span>`;
}

export function sessionRow(s) {
  const who = s.engineer ? `${escapeHtml(s.engineer.full_name)} <span class="muted mono">${escapeHtml(s.engineer.engineer_id)}</span>`
    : '<span class="muted">—</span>';
  return `<tr>
    <td>${fmtDate(s.created_at)}</td>
    <td>${s.direction === "SALIDA" ? "Salida" : "Entrada"}</td>
    <td>${who}</td>
    <td class="mono">${escapeHtml(s.card_uid)}</td>
    <td>${badge(s.state)}</td>
    <td>${s.reason ? escapeHtml(s.reason) : '<span class="muted">—</span>'}</td>
    <td>${s.face_score == null ? "—" : s.face_score.toFixed(2)}</td>
  </tr>`;
}

export const SESSION_HEAD = `<tr><th>Fecha</th><th>Sentido</th><th>Ingeniero</th><th>Tarjeta</th>
  <th>Estado</th><th>Motivo</th><th>Rostro</th></tr>`;

export function alertRow(a, { ack = false } = {}) {
  return `<tr data-id="${a.id}">
    <td>${fmtDate(a.created_at)}</td>
    <td>${badge(a.severity)}</td>
    <td class="mono">${escapeHtml(a.type)}</td>
    <td>${escapeHtml(a.message)}</td>
    <td>${a.acknowledged_at ? `<span class="muted">Atendida ${fmtDate(a.acknowledged_at)}</span>`
      : ack ? '<button class="btn admin-only" data-ack>Atender</button>' : badge("Abierta", "warn")}</td>
  </tr>`;
}

export const ALERT_HEAD = "<tr><th>Fecha</th><th>Severidad</th><th>Tipo</th><th>Mensaje</th><th>Estado</th></tr>";

export function emptyRow(cols, text = "Sin datos") {
  return `<tr><td colspan="${cols}" class="empty">${text}</td></tr>`;
}

// Motivos de denegación (espejo de backend/app/services/access_engine.REASON_TEXT).
export const REASON_TEXT = {
  UNKNOWN_CARD: "Tarjeta no registrada en el sistema",
  CARD_NOT_ACTIVE: "La tarjeta no está activa (bloqueada, perdida o dada de baja)",
  CARD_LOCKED: "Tarjeta bloqueada temporalmente por intentos fallidos",
  CARD_NOT_LINKED: "La tarjeta no está vinculada a ningún ingeniero",
  ENGINEER_INACTIVE: "El ingeniero no está activo (inactivo, suspendido o eliminado)",
  NO_VALID_AUTH: "No existe ninguna autorización para esta tarjeta en esta área",
  REQUEST_PENDING: "La solicitud de autorización aún no ha sido aprobada",
  AUTH_EXPIRED: "La autorización ha vencido",
  AUTH_REVOKED: "La autorización fue revocada",
  AUTH_NOT_STARTED: "La ventana de la autorización aún no ha comenzado",
  AUTH_REJECTED: "La solicitud de autorización fue rechazada",
  NO_FACE_ENROLLED: "El ingeniero no tiene rostro registrado",
  FACE_MISMATCH: "El rostro no coincide con el titular de la tarjeta",
  LIVENESS_FAILED: "Prueba de vida fallida (imágenes estáticas o idénticas)",
  FACE_NOT_DETECTED: "No se detectó un rostro en la cámara",
  MULTIPLE_FACES: "Hay más de un rostro frente a la cámara",
  MODEL_MISMATCH: "Las muestras faciales se registraron con otro modelo",
  BIOMETRIC_ERROR: "Error en la verificación facial",
  BAD_FRAME_COUNT: "Número de capturas incorrecto",
  PRESENCE_LOST: "La persona se alejó de la puerta antes de la decisión",
  SENSOR_ERROR: "Lectura del sensor de presencia no válida",
  DEVICE_DISABLED: "Dispositivo deshabilitado por un administrador",
  TIMEOUT: "Tiempo de verificación agotado",
  SESSION_SUPERSEDED: "Se inició otro intento en la misma puerta",
  NOBODY_INSIDE: "Botón de salida pulsado sin nadie dentro: la puerta no se abre",
  // Entrada principal (credencial QR), ver docs/contrato-qr-dht11.md §2.
  QR_INVALID: "El código QR no es una credencial válida de Telecom Conecta",
  QR_UNKNOWN: "Credencial QR no registrada en el sistema",
  QR_REVOKED: "La credencial QR fue revocada",
  QR_EXPIRED: "La credencial QR ha vencido",
  DEVICE_OFFLINE: "El dispositivo de la entrada está fuera de línea: la puerta permanece cerrada",
  RATE_LIMITED: "Demasiados intentos seguidos: espere un momento",
};

// Zonas y métodos de la bitácora (contrato QR + DHT11 §0 y §6).
export const ZONE_LABEL = {
  ENTRADA_PRINCIPAL: "Entrada principal",
  SALA_SERVIDORES: "Sala de servidores",
};
export const METHOD_LABEL = { QR: "Código QR", "RFID+ROSTRO": "RFID + rostro", BOTON_SALIDA: "Botón de salida" };
export const zoneText = (code, name = null) => (code ? ZONE_LABEL[code] ?? name ?? code : name ?? "—");
export const methodText = (m) => (m ? METHOD_LABEL[m] ?? m : "—");

export const reasonText = (code) => (code ? REASON_TEXT[code] ?? code : "");
