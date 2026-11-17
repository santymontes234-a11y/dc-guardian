// Gráfica ligera en SVG (sin librerías) de una serie temporal con líneas de umbral.
//   import { lineChart } from "/js/env-chart.js";
//   lineChart(svgEl, { points: [{t: Date, v: 24.5}], minutes: 60, unit: "°C",
//                      domain: [10, 45], thresholds: [{ value: 27, label: "Alta", tone: "warn" }] });
// Todo se construye con createElementNS + textContent: ningún dato se interpreta como HTML.

const NS = "http://www.w3.org/2000/svg";
const W = 600;
const H = 180;
const PAD = { l: 40, r: 12, t: 12, b: 24 };

function el(name, attrs = {}, text = null) {
  const node = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
  if (text !== null) node.textContent = text;
  return node;
}

export function lineChart(svg, { points, minutes = 60, unit = "", domain = [0, 100], thresholds = [], label = "" }) {
  const now = Date.now();
  const t0 = now - minutes * 60_000;
  const valid = points.filter((p) => p.v !== null && p.v !== undefined && Number.isFinite(p.v) && p.t >= t0);
  let [lo, hi] = domain;
  for (const p of valid) { lo = Math.min(lo, Math.floor(p.v - 1)); hi = Math.max(hi, Math.ceil(p.v + 1)); }
  for (const th of thresholds) { lo = Math.min(lo, th.value - 1); hi = Math.max(hi, th.value + 1); }
  const x = (t) => PAD.l + ((t - t0) / (now - t0)) * (W - PAD.l - PAD.r);
  const y = (v) => PAD.t + (1 - (v - lo) / (hi - lo || 1)) * (H - PAD.t - PAD.b);

  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("role", "img");
  const lastV = valid.length ? valid[valid.length - 1].v : null;
  svg.setAttribute("aria-label", `${label}: últimos ${minutes} minutos, ${valid.length} lecturas`
    + (lastV === null ? "" : `, última ${lastV}${unit}`));
  svg.replaceChildren();

  // Rejilla horizontal y eje Y
  const steps = 4;
  for (let i = 0; i <= steps; i += 1) {
    const v = lo + ((hi - lo) * i) / steps;
    svg.append(el("line", { x1: PAD.l, x2: W - PAD.r, y1: y(v), y2: y(v), class: "grid" }));
    svg.append(el("text", { x: PAD.l - 6, y: y(v) + 4, class: "axis", "text-anchor": "end" }, `${Math.round(v)}`));
  }
  // Eje X: marcas cada 15 min
  for (let m = 0; m <= minutes; m += 15) {
    const t = t0 + m * 60_000;
    svg.append(el("text", { x: x(t), y: H - 6, class: "axis", "text-anchor": m === 0 ? "start" : m === minutes ? "end" : "middle" },
      m === minutes ? "ahora" : `-${minutes - m} min`));
  }
  // Umbrales
  for (const th of thresholds) {
    svg.append(el("line", { x1: PAD.l, x2: W - PAD.r, y1: y(th.value), y2: y(th.value), class: `threshold ${th.tone ?? "warn"}` }));
    svg.append(el("text", { x: W - PAD.r - 4, y: y(th.value) - 4, class: `th-label ${th.tone ?? "warn"}`, "text-anchor": "end" },
      `${th.label} ${th.value}${unit}`));
  }
  // Serie (se corta donde hay huecos de más de 60 s o lecturas con error)
  let d = "";
  let prev = null;
  for (const p of points) {
    if (p.t < t0) continue;
    const ok = p.v !== null && p.v !== undefined && Number.isFinite(p.v);
    if (!ok) { prev = null; continue; }
    d += `${prev && p.t - prev.t <= 60_000 ? "L" : "M"}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)} `;
    prev = p;
  }
  if (d) svg.append(el("path", { d: d.trim(), class: "series" }));
  if (valid.length) {
    const p = valid[valid.length - 1];
    svg.append(el("circle", { cx: x(p.t), cy: y(p.v), r: 4, class: "dot" }));
  } else {
    svg.append(el("text", { x: W / 2, y: H / 2, class: "axis", "text-anchor": "middle" }, "Sin lecturas en este periodo"));
  }
}
