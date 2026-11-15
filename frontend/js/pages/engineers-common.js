// Utilidades compartidas por las páginas del Registro 1.
import { escapeHtml } from "/js/api.js";

export const STATUS = {
  ACTIVO: { label: "Activo", tone: "ok" },
  INACTIVO: { label: "Inactivo", tone: "muted" },
  SUSPENDIDO: { label: "Suspendido", tone: "danger" },
  ELIMINADO: { label: "Eliminado", tone: "muted" },
};

export function statusBadge(status) {
  const s = STATUS[status] ?? { label: status, tone: "muted" };
  return `<span class="badge badge-${s.tone}">${escapeHtml(s.label)}</span>`;
}

export function initials(name) {
  const parts = String(name ?? "").replace(/[\[\]]/g, "").trim().split(/\s+/).filter(Boolean);
  return escapeHtml(((parts[0]?.[0] ?? "?") + (parts[1]?.[0] ?? "")).toUpperCase());
}

export function bioBadge(eng) {
  return eng.has_face
    ? `<span class="en-bio" data-state="ok"><i></i>${eng.face_samples} muestras</span>`
    : '<span class="en-bio" data-state="none"><i></i>Sin rostro</span>';
}

export function fmtDay(iso) {
  return iso ? new Date(iso).toLocaleDateString("es", { dateStyle: "medium" }) : "—";
}

export function debounce(fn, ms = 250) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}
