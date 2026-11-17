// Bitácora unificada de accesos (contrato QR + DHT11 §6): entrada principal (QR) y sala de
// servidores (RFID + rostro).
//   import { fetchAccessLog, logRow, LOG_HEAD } from "/js/access-log.js";
//   const page = await fetchAccessLog({ zone: "ENTRADA_PRINCIPAL", result: "DENIED", method: "QR", limit: 50 });
//
// Usa GET /access-log. Si el backend aún no lo expone (404/405), recurre a /access-sessions
// (solo sala de servidores) para que la pantalla siga siendo útil.
import { api, ApiError, escapeHtml, fmtDate } from "/js/api.js";
import { REASON_TEXT, badge, methodText, zoneText } from "/js/ui.js";

const GRANTED_STATES = new Set(["GRANTED", "OPENED", "CLOSED"]);
let legacy = false; // recuerda que /access-log no existe para no repetir la petición fallida

function pick(obj, ...keys) {
  for (const k of keys) if (obj?.[k] !== undefined && obj?.[k] !== null) return obj[k];
  return null;
}

/** Fila de la API (nueva o heredada) → forma común para pintar. */
export function normalizeLogRow(r) {
  const res = r.result && typeof r.result === "object" ? r.result : { value: r.result };
  const zone = r.zone && typeof r.zone === "object" ? r.zone : { code: r.zone ?? r.area_code ?? r.area ?? null };
  const state = pick(r, "state");
  let result = pick(res, "value", "result", "code", "status");
  if (!result && state) result = GRANTED_STATES.has(state) ? "GRANTED" : state;
  const reasonCode = pick(res, "reason_code") ?? pick(r, "reason_code");
  return {
    at: pick(r, "at", "created_at"),
    person: typeof r.person === "object" && r.person ? pick(r.person, "full_name", "name")
      : pick(r, "person", "display_name") ?? r.engineer?.full_name ?? null,
    personCode: (typeof r.engineer_id === "string" ? r.engineer_id : null) ?? r.engineer?.engineer_id ?? null,
    position: pick(r, "position") ?? r.engineer?.position ?? (typeof r.person === "object" ? r.person?.position : null),
    zoneCode: zone.code ?? (state ? "SALA_SERVIDORES" : null),
    zoneName: zone.name ?? null,
    method: pick(r, "method") ?? (r.card_uid !== undefined ? "RFID+ROSTRO" : null),
    direction: pick(r, "direction"),
    result,
    state,
    reasonCode,
    reason: pick(res, "reason") ?? pick(r, "reason"),
  };
}

async function fetchLegacy({ zone, result, method, limit }) {
  if (zone === "ENTRADA_PRINCIPAL" || method === "QR") return { items: [], total: 0, legacy: true };
  const state = result === "DENIED" ? "DENIED" : result === "GRANTED" ? "CLOSED" : undefined;
  const page = await api.get("/access-sessions", { state, limit });
  return { items: page.items.map(normalizeLogRow), total: page.total, legacy: true };
}

/** Devuelve `{ items: [filas normalizadas], total, legacy }`. Lanza ApiError en otros fallos. */
export async function fetchAccessLog({ zone = "", result = "", method = "", limit = 50 } = {}) {
  const q = { zone, result, method, limit };
  if (!legacy) {
    try {
      const page = await api.get("/access-log", q);
      const items = Array.isArray(page) ? page : page.items ?? [];
      return { items: items.map(normalizeLogRow), total: page.total ?? items.length, legacy: false };
    } catch (err) {
      if (!(err instanceof ApiError) || ![404, 405].includes(err.status)) throw err;
      legacy = true;
    }
  }
  return fetchLegacy(q);
}

const DIRECTION = { ENTRADA: "Entrada", SALIDA: "Salida" };

function resultBadge(row) {
  if (row.result === "GRANTED") return badge("Permitido", "ok");
  if (row.result === "DENIED") return badge("Denegado", "danger");
  return badge(row.state ?? row.result ?? "—");
}

export const LOG_HEAD = `<tr><th>Fecha y hora</th><th>Persona</th><th>Puesto</th><th>Zona</th><th>Método</th>
  <th>Dirección</th><th>Resultado</th><th>Motivo</th></tr>`;
export const LOG_COLS = 8;

export function logRow(row) {
  const who = row.person
    ? `${escapeHtml(row.person)}${row.personCode ? ` <span class="muted mono">${escapeHtml(row.personCode)}</span>` : ""}`
    : '<span class="muted">Desconocida</span>';
  const reason = (row.reasonCode && REASON_TEXT[row.reasonCode]) || row.reason || row.reasonCode;
  return `<tr>
    <td>${fmtDate(row.at)}</td>
    <td>${who}</td>
    <td>${row.position ? escapeHtml(row.position) : '<span class="muted">—</span>'}</td>
    <td>${escapeHtml(zoneText(row.zoneCode, row.zoneName))}</td>
    <td>${badge(methodText(row.method), row.method === "QR" ? "info" : "muted")}</td>
    <td>${escapeHtml(DIRECTION[row.direction] ?? row.direction ?? "Entrada")}</td>
    <td>${resultBadge(row)}</td>
    <td>${reason ? escapeHtml(reason) : '<span class="muted">—</span>'}</td>
  </tr>`;
}
