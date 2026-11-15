import { ready } from "/js/layout.js";
import { api, escapeHtml, guarded } from "/js/api.js";
import { bioBadge, debounce, fmtDay, initials, statusBadge } from "/js/pages/engineers-common.js";

await ready;

const LIMIT = 20;
const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const state = { q: params.get("q") ?? "", status: params.get("status") ?? "", has_face: params.get("face") ?? "", offset: 0 };

$("f-q").value = state.q;
$("f-status").value = state.status;
$("f-face").value = state.has_face;

async function loadStats() {
  const s = await guarded(() => api.get("/engineers/stats"));
  if (!s) return;
  const total = s.ACTIVO + s.INACTIVO + s.SUSPENDIDO;
  $("st-total").textContent = total;
  $("st-active").textContent = s.ACTIVO;
  $("st-suspended").textContent = s.SUSPENDIDO;
  $("st-noface").textContent = total - s.CON_ROSTRO;
}

function row(e) {
  const erased = e.status === "ELIMINADO";
  const cards = e.cards.length ? e.cards.map((c) => `<span class="mono">${escapeHtml(c.uid)}</span>`).join("<br>") : '<span class="muted">—</span>';
  return `<tr tabindex="0" data-id="${e.id}" aria-label="Ver ${escapeHtml(e.full_name)}">
    <td><div class="en-who"><span class="en-avatar">${initials(e.full_name)}</span>
      <div><b>${escapeHtml(e.full_name)}</b><small>${erased ? "Datos personales eliminados" : escapeHtml(e.institutional_email)}</small></div></div></td>
    <td><span class="en-code">${escapeHtml(e.engineer_id)}</span></td>
    <td>${escapeHtml(e.department)}<br><small class="muted">${escapeHtml(e.position)}</small></td>
    <td>${statusBadge(e.status)}</td>
    <td>${bioBadge(e)}</td>
    <td>${cards}</td>
    <td class="muted">${fmtDay(e.registration_date)}</td>
  </tr>`;
}

async function load() {
  const query = { limit: LIMIT, offset: state.offset, q: state.q, status: state.status, has_face: state.has_face };
  const page = await guarded(() => api.get("/engineers", query));
  if (!page) return;
  const rows = $("rows");
  rows.innerHTML = page.items.length
    ? page.items.map(row).join("")
    : `<tr><td colspan="7" class="empty">${state.q || state.status || state.has_face
      ? "Ningún ingeniero coincide con los filtros."
      : 'Aún no hay ingenieros. <a class="admin-only" href="/pages/engineer-new.html">Registra el primero</a>.'}</td></tr>`;
  $("result-count").textContent = `${page.total} resultado${page.total === 1 ? "" : "s"}`;
  const from = page.total ? page.offset + 1 : 0;
  $("page-info").textContent = `${from}–${page.offset + page.items.length} de ${page.total}`;
  $("prev").disabled = page.offset === 0;
  $("next").disabled = page.offset + page.items.length >= page.total;
}

function syncUrl() {
  const p = new URLSearchParams();
  if (state.q) p.set("q", state.q);
  if (state.status) p.set("status", state.status);
  if (state.has_face) p.set("face", state.has_face);
  history.replaceState(null, "", `${location.pathname}${p.size ? `?${p}` : ""}`);
}

function refilter() { state.offset = 0; syncUrl(); load(); }

$("f-q").addEventListener("input", debounce((e) => { state.q = e.target.value.trim(); refilter(); }));
$("f-status").addEventListener("change", (e) => { state.status = e.target.value; refilter(); });
$("f-face").addEventListener("change", (e) => { state.has_face = e.target.value; refilter(); });
$("prev").addEventListener("click", () => { state.offset = Math.max(0, state.offset - LIMIT); load(); });
$("next").addEventListener("click", () => { state.offset += LIMIT; load(); });

const open = (tr) => tr?.dataset.id && (location.href = `/pages/engineer.html?id=${tr.dataset.id}`);
$("rows").addEventListener("click", (e) => { if (!e.target.closest("a")) open(e.target.closest("tr")); });
$("rows").addEventListener("keydown", (e) => { if (e.key === "Enter") open(e.target.closest("tr")); });

loadStats();
load();
