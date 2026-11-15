// Cliente HTTP compartido de DC Guardian. Contrato estable: ver docs/api.md § Frontend.
//   import { api, ApiError } from "/js/api.js";
//   const page = await api.get("/requests", { status: "PENDIENTE" });
// - Rutas relativas a /api/v1. La sesión viaja en la cookie HttpOnly (no hay token en JS).
// - 401 fuera del login → redirige a /index.html?next=<página actual>.
// - Cualquier respuesta no 2xx lanza ApiError { status, code, message, details, correlationId }.

const BASE = "/api/v1";

export class ApiError extends Error {
  constructor(status, code, message, details = null, correlationId = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.correlationId = correlationId;
  }
}

function buildUrl(path, query) {
  const url = new URL(BASE + path, window.location.origin);
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v);
    }
  }
  return url.pathname + url.search;
}

function redirectToLogin() {
  if (window.location.pathname === "/" || window.location.pathname.endsWith("/index.html")) return;
  const next = encodeURIComponent(window.location.pathname + window.location.search + window.location.hash);
  window.location.href = `/index.html?next=${next}`;
}

async function request(method, path, { body, query, form, noRedirect = false } = {}) {
  const init = { method, credentials: "same-origin", headers: { Accept: "application/json" } };
  if (form) {
    init.body = form; // FormData: el navegador pone el Content-Type con boundary
  } else if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }

  let res;
  try {
    res = await fetch(buildUrl(path, query), init);
  } catch (err) {
    throw new ApiError(0, "NETWORK_ERROR", "No se pudo contactar con el servidor");
  }

  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);

  if (!res.ok) {
    const e = data?.error ?? {};
    if (res.status === 401 && !noRedirect) redirectToLogin();
    throw new ApiError(res.status, e.code ?? "HTTP_ERROR", e.message ?? res.statusText, e.details ?? null,
      e.correlation_id ?? res.headers.get("X-Correlation-Id"));
  }
  return data;
}

export const api = {
  get: (path, query, opts) => request("GET", path, { query, ...opts }),
  post: (path, body, opts) => request("POST", path, { body: body ?? {}, ...opts }),
  patch: (path, body, opts) => request("PATCH", path, { body, ...opts }),
  del: (path, opts) => request("DELETE", path, opts),
  upload: (path, formData, opts) => request("POST", path, { form: formData, ...opts }),
};

// Utilidades de presentación compartidas.
export function fmtDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("es", { dateStyle: "short", timeStyle: "medium" });
}

export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

/** Muestra un aviso breve (tipo: "ok" | "error" | "info"). */
export function toast(message, type = "info") {
  let box = document.getElementById("toasts");
  if (!box) {
    box = document.createElement("div");
    box.id = "toasts";
    document.body.appendChild(box);
  }
  const el = document.createElement("div");
  el.className = `toast toast-${type}`;
  el.textContent = message;
  box.appendChild(el);
  setTimeout(() => el.remove(), 5000);
}

/** Envuelve una acción: muestra el error de la API como aviso y lo devuelve como null. */
export async function guarded(fn) {
  try {
    return await fn();
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) return null;
    toast(err.message ?? String(err), "error");
    return null;
  }
}
