// Cliente del WebSocket /ws/events con reconexión automática.
//   import { connectEvents } from "/js/ws.js";
//   const events = connectEvents({ kioskToken });   // sin token → cookie de administrador
//   events.on("access.*", (evt) => …);              // evt = { type, ts, data }
//   events.on("status", (s) => …);                  // "open" | "closed"

export function connectEvents({ kioskToken = null } = {}) {
  const handlers = new Map();
  let ws = null;
  let retry = 1000;
  let stopped = false;

  const emit = (type, payload) => {
    for (const [pattern, fns] of handlers) {
      const match = pattern === type || pattern === "*" ||
        (pattern.endsWith(".*") && type.startsWith(pattern.slice(0, -1)));
      if (match) fns.forEach((fn) => fn(payload));
    }
  };

  const open = () => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws/events`);
    ws.onopen = () => {
      // El token del kiosco va en el primer mensaje, nunca en la URL (acabaría en los logs).
      if (kioskToken) ws.send(JSON.stringify({ kiosk_token: kioskToken }));
      retry = 1000;
      emit("status", "open");
    };
    ws.onmessage = (m) => {
      let evt;
      try { evt = JSON.parse(m.data); } catch { return; }
      emit(evt.type, evt);
    };
    ws.onclose = (e) => {
      emit("status", "closed");
      if (stopped || e.code === 4401) return; // 4401 = sin autorización: no insistir
      setTimeout(open, retry);
      retry = Math.min(retry * 2, 15000);
    };
  };
  open();

  return {
    on(pattern, fn) {
      if (!handlers.has(pattern)) handlers.set(pattern, new Set());
      handlers.get(pattern).add(fn);
      return this;
    },
    close() { stopped = true; ws?.close(); },
  };
}
