// Autenticación de las pantallas de kiosco (mismo esquema que /pages/kiosk.html): token de kiosco
// en la cabecera X-Kiosk-Token o, si no hay token, la sesión de administrador (cookie HttpOnly).
// El token se guarda en sessionStorage con la misma clave que el kiosco facial y nunca se deja
// en la URL.
//   import { kioskApi, kioskToken, setKioskToken } from "/js/kiosk-auth.js";
//   await kioskApi.post("/kiosk/entrance/scan", { qr_text });

import { api } from "/js/api.js";

const KEY = "dcg-kiosk-token";

function safeGet(k) { try { return sessionStorage.getItem(k); } catch { return null; } }
function safeSet(k, v) { try { sessionStorage.setItem(k, v); } catch { /* sin almacenamiento */ } }

const params = new URLSearchParams(location.search);
let token = params.get("token") || safeGet(KEY);
if (params.has("token")) {
  if (token) safeSet(KEY, token);
  params.delete("token");
  const q = params.toString();
  history.replaceState(null, "", `${location.pathname}${q ? `?${q}` : ""}`);
}

export const kioskToken = () => token;

export function setKioskToken(value) {
  token = String(value ?? "").trim() || null;
  safeSet(KEY, token ?? "");
}

const opts = () => ({ noRedirect: true, headers: token ? { "X-Kiosk-Token": token } : null });

/** Igual que `api`, pero con la autenticación de kiosco y sin redirigir al login en 401. */
export const kioskApi = {
  get: (path, query) => api.get(path, query, opts()),
  post: (path, body) => api.post(path, body, opts()),
};
