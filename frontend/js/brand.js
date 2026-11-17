// Marca de la empresa asignada y fecha visible (requisito: deben verse en las capturas).
//   import { COMPANY, startClock } from "/js/brand.js";
//   startClock(element, { withTime: true });

export const COMPANY = "Telecom Conecta";
export const PRODUCT = "DC Guardian";

export function fmtToday(date = new Date()) {
  return date.toLocaleDateString("es", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
}

export function fmtClock(date = new Date()) {
  return date.toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/** Mantiene `el` con la fecha (y hora) actual. Devuelve una función para detenerlo. */
export function startClock(el, { withTime = true } = {}) {
  if (!el) return () => {};
  const tick = () => {
    const now = new Date();
    const text = withTime ? `${fmtToday(now)} · ${fmtClock(now)}` : fmtToday(now);
    el.textContent = text.charAt(0).toUpperCase() + text.slice(1);
    el.setAttribute("datetime", now.toISOString());
  };
  tick();
  const timer = setInterval(tick, withTime ? 1000 : 60000);
  return () => clearInterval(timer);
}
