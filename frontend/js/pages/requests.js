// Solicitudes de acceso (Registro 2): listado por estado, detalle, decisión y alta.
import { api, ApiError, escapeHtml as h, toast, guarded } from "/js/api.js";
import { ready } from "/js/layout.js";

const admin = await ready;
const isAdmin = admin.role === "admin";
const PAGE = 20;

const STATUS = {
  PENDIENTE: { label: "Pendiente", badge: "badge-warn", dot: "var(--warn)" },
  APROBADA: { label: "Aprobada", badge: "badge-ok", dot: "var(--ok)" },
  RECHAZADA: { label: "Rechazada", badge: "badge-danger", dot: "var(--danger)" },
  EXPIRADA: { label: "Expirada", badge: "badge-muted", dot: "var(--text-muted)" },
  REVOCADA: { label: "Revocada", badge: "badge-danger", dot: "var(--danger)" },
  FINALIZADA: { label: "Finalizada", badge: "badge-info", dot: "var(--info)" },
};
const AUDIT_LABEL = {
  "request.created": "Solicitud creada",
  "request.approved": "Aprobada · autorización temporal generada",
  "request.rejected": "Rechazada",
  "request.revoked": "Revocada",
  "request.finalized": "Finalizada manualmente",
  "request.finished": "Finalizada (fin de ventana)",
  "request.expired": "Expirada",
  "request.self_review_blocked": "Intento de autoaprobación bloqueado",
};

const $ = (sel) => document.querySelector(sel);
const state = { tab: "PENDIENTE", status: "", q: "", offset: 0, total: 0 };

// ----------------------------------------------------------------- formato
const dFmt = new Intl.DateTimeFormat("es", { weekday: "short", day: "2-digit", month: "short", year: "numeric" });
const tFmt = new Intl.DateTimeFormat("es", { hour: "2-digit", minute: "2-digit" });
const dtFmt = new Intl.DateTimeFormat("es", { dateStyle: "medium", timeStyle: "short" });
const fmtDT = (iso) => (iso ? dtFmt.format(new Date(iso)) : "—");
const sameDay = (a, b) => a.toDateString() === b.toDateString();

function fmtWindow(r) {
  const s = new Date(r.start_at), e = new Date(r.end_at);
  const end = sameDay(s, e) ? tFmt.format(e) : `${tFmt.format(e)} (+1 día)`;
  return `${tFmt.format(s)} – ${end}<small>${dFmt.format(s)}</small>`;
}
function fmtDuration(min) {
  const hh = Math.floor(min / 60), mm = min % 60;
  return hh ? `${hh} h${mm ? ` ${mm} min` : ""}` : `${mm} min`;
}
function badge(status) {
  const s = STATUS[status] ?? { label: status, badge: "badge-muted" };
  return `<span class="badge ${s.badge}">${h(s.label)}</span>`;
}
const adminName = (a) => (a ? `${h(a.full_name)} <span class="muted">(@${h(a.username)})</span>` : "Sistema");
const isOwn = (r) => admin.engineer_id != null && admin.engineer_id === r.engineer.id;

// ----------------------------------------------------------------- resumen y listado
async function loadStats() {
  const st = await guarded(() => api.get("/requests/stats"));
  if (!st) return;
  const b = st.by_status;
  $("#st-pending").textContent = b.PENDIENTE;
  $("#st-inforce").textContent = st.in_force;
  $("#st-approved").textContent = b.APROBADA;
  $("#st-rejected").textContent = b.RECHAZADA;
  for (const k of ["PENDIENTE", "APROBADA", "RECHAZADA"]) $(`#tc-${k}`).textContent = b[k] || "";
  $("#tc-ALL").textContent = st.total || "";
}

function rowActions(r) {
  const view = `<button type="button" class="btn" data-act="view">Ver</button>`;
  if (!isAdmin) return view;
  if (r.status === "PENDIENTE" && !isOwn(r)) {
    return `<button type="button" class="btn btn-ok" data-act="approve">Aprobar</button>
            <button type="button" class="btn btn-danger" data-act="reject">Rechazar</button>`;
  }
  if (r.status === "APROBADA") return `${view}<button type="button" class="btn btn-danger" data-act="revoke">Revocar</button>`;
  return view;
}

async function loadList() {
  const status = state.tab === "ALL" ? state.status : state.tab;
  const page = await guarded(() => api.get("/requests", { status, q: state.q, limit: PAGE, offset: state.offset }));
  if (!page) return;
  state.total = page.total;
  const tbody = $("#rows");
  tbody.innerHTML = page.items.map((r) => `
    <tr tabindex="0" data-id="${r.id}">
      <td class="mono">#${r.id}</td>
      <td class="rq-who"><strong>${h(r.engineer.full_name)}</strong><small>${h(r.engineer.engineer_id)}</small></td>
      <td class="mono">${h(r.card.uid)}</td>
      <td>${h(r.area.name)}</td>
      <td class="rq-window">${fmtWindow(r)}</td>
      <td>${fmtDuration(r.duration_minutes)}</td>
      <td>${badge(r.status)}${r.in_force ? '<span class="rq-live">Vigente</span>' : ""}</td>
      <td><div class="rq-actions">${rowActions(r)}</div></td>
    </tr>`).join("");
  const empty = page.items.length === 0;
  $("#empty").hidden = !empty;
  $("#empty").textContent = state.q ? "Ninguna solicitud coincide con la búsqueda." : "No hay solicitudes en esta vista.";
  const from = empty ? 0 : state.offset + 1;
  $("#pager-info").textContent = `${from}–${state.offset + page.items.length} de ${page.total}`;
  $("#prev").disabled = state.offset === 0;
  $("#next").disabled = state.offset + PAGE >= page.total;
}

const refresh = () => Promise.all([loadStats(), loadList()]);

document.querySelectorAll(".rq-tabs [role=tab]").forEach((btn) =>
  btn.addEventListener("click", () => {
    state.tab = btn.dataset.tab;
    state.offset = 0;
    document.querySelectorAll(".rq-tabs [role=tab]").forEach((b) => b.setAttribute("aria-selected", String(b === btn)));
    $("#f-status").hidden = state.tab !== "ALL";
    loadList();
  }));
$("#f-status").addEventListener("change", (e) => { state.status = e.target.value; state.offset = 0; loadList(); });
let qTimer;
$("#f-q").addEventListener("input", (e) => {
  clearTimeout(qTimer);
  qTimer = setTimeout(() => { state.q = e.target.value.trim(); state.offset = 0; loadList(); }, 250);
});
$("#prev").addEventListener("click", () => { state.offset = Math.max(0, state.offset - PAGE); loadList(); });
$("#next").addEventListener("click", () => { state.offset += PAGE; loadList(); });

$("#rows").addEventListener("click", (e) => {
  const tr = e.target.closest("tr[data-id]");
  if (!tr) return;
  const id = Number(tr.dataset.id);
  const act = e.target.closest("[data-act]")?.dataset.act ?? "view";
  if (act === "view") openDetail(id);
  else decide(id, act);
});
$("#rows").addEventListener("keydown", (e) => {
  const tr = e.target.closest("tr[data-id]");
  if (tr && e.key === "Enter" && e.target === tr) openDetail(Number(tr.dataset.id));
});

// ----------------------------------------------------------------- detalle
const drawer = $("#drawer"), drawerBg = $("#drawer-bg");
let current = null;

function closeDrawer() {
  drawer.classList.remove("open");
  drawer.setAttribute("aria-hidden", "true");
  drawerBg.hidden = true;
  current = null;
}
$("#d-close").addEventListener("click", closeDrawer);
drawerBg.addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && drawer.classList.contains("open") && !document.querySelector("dialog[open]")) closeDrawer();
});

function banner(r) {
  const now = Date.now(), start = Date.parse(r.start_at), end = Date.parse(r.end_at);
  if (r.status === "APROBADA") {
    if (r.in_force) return `<div class="rq-banner rq-banner-ok">Autorización <b>vigente</b>: el acceso se permite hasta ${h(fmtDT(r.end_at))}.</div>`;
    if (now < start) return `<div class="rq-banner rq-banner-ok">Autorización temporal generada. Entrará en vigor el ${h(fmtDT(r.start_at))}.</div>`;
    if (now < end) return `<div class="rq-banner rq-banner-warn">Aprobada, pero <b>no vigente</b>: la tarjeta o el ingeniero ya no están activos.</div>`;
  }
  if (r.status === "PENDIENTE") {
    if (isOwn(r)) return `<div class="rq-banner rq-banner-warn">Esta solicitud es tuya: debe decidirla otro administrador.</div>`;
    if (now >= end) return `<div class="rq-banner rq-banner-warn">La ventana ya terminó; se marcará como expirada.</div>`;
    return `<div class="rq-banner rq-banner-warn">Pendiente de decisión. No concede acceso.</div>`;
  }
  if (["RECHAZADA", "REVOCADA"].includes(r.status)) return `<div class="rq-banner rq-banner-danger">Esta solicitud no permite accesos.</div>`;
  return "";
}

function detailHtml(r, trail) {
  const decision = r.reviewer || r.reviewed_at ? `
    <section class="rq-section"><h3>Decisión</h3><dl class="rq-dl">
      <dt>Responsable</dt><dd>${adminName(r.reviewer)}</dd>
      <dt>Fecha</dt><dd>${h(fmtDT(r.reviewed_at))}</dd>
      <dt>Notas</dt><dd>${r.review_notes ? h(r.review_notes) : '<span class="muted">—</span>'}</dd>
    </dl></section>` : "";
  const closing = r.closed_at ? `
    <section class="rq-section"><h3>Cierre</h3><dl class="rq-dl">
      <dt>Cerrada por</dt><dd>${adminName(r.closer)}</dd>
      <dt>Fecha</dt><dd>${h(fmtDT(r.closed_at))}</dd>
      <dt>Notas</dt><dd>${r.close_notes ? h(r.close_notes) : '<span class="muted">—</span>'}</dd>
    </dl></section>` : "";
  const items = (trail ?? []).slice().reverse().map((e) => {
    const to = e.details?.to;
    const dot = to ? STATUS[to]?.dot : e.action.endsWith("blocked") ? "var(--danger)" : "var(--primary)";
    const who = e.actor_type === "admin" ? `admin #${h(e.actor_id)}` : h(e.actor_type === "system" ? "sistema" : e.actor_type);
    const notes = e.details?.notes ? ` — “${h(e.details.notes)}”` : "";
    return `<li style="--dot:${dot}">${h(AUDIT_LABEL[e.action] ?? e.action)}${notes}<small>${h(fmtDT(e.ts))} · ${who}</small></li>`;
  }).join("");
  return `
    ${banner(r)}
    <section class="rq-section"><h3>Ingeniero y tarjeta</h3><dl class="rq-dl">
      <dt>Ingeniero</dt><dd>${h(r.engineer.full_name)} <span class="mono muted">${h(r.engineer.engineer_id)}</span></dd>
      <dt>Departamento</dt><dd>${h(r.engineer.department)}</dd>
      <dt>Estado</dt><dd>${h(r.engineer.status)}</dd>
      <dt>UID RFID</dt><dd class="mono">${h(r.card.uid)} <span class="muted">(${h(r.card.status)})</span></dd>
    </dl></section>
    <section class="rq-section"><h3>Acceso solicitado</h3><dl class="rq-dl">
      <dt>Área</dt><dd>${h(r.area.name)} <span class="mono muted">${h(r.area.code)}</span></dd>
      <dt>Inicio</dt><dd>${h(fmtDT(r.start_at))}</dd>
      <dt>Finalización</dt><dd>${h(fmtDT(r.end_at))}</dd>
      <dt>Duración</dt><dd>${fmtDuration(r.duration_minutes)}</dd>
      <dt>Usos</dt><dd>${r.use_count}${r.first_used_at ? ` · primero ${h(fmtDT(r.first_used_at))}` : ""}</dd>
    </dl></section>
    <section class="rq-section"><h3>Motivo</h3><p class="rq-quote">${h(r.reason)}</p></section>
    ${r.observations ? `<section class="rq-section"><h3>Observaciones</h3><p class="rq-quote">${h(r.observations)}</p></section>` : ""}
    ${decision}${closing}
    <section class="rq-section"><h3>Historial de la solicitud</h3>
      ${items ? `<ol class="rq-timeline">${items}</ol>` : '<p class="muted">Sin eventos.</p>'}
      <p class="muted rq-small">Registrada por ${adminName(r.creator)} el ${h(fmtDT(r.created_at))}.</p>
    </section>`;
}

function detailActions(r) {
  if (!isAdmin) return "";
  if (r.status === "PENDIENTE" && !isOwn(r)) {
    return `<button type="button" class="btn btn-danger" data-act="reject">Rechazar</button>
            <button type="button" class="btn btn-primary" data-act="approve">Aprobar y generar autorización</button>`;
  }
  if (r.status === "APROBADA") {
    return `<button type="button" class="btn" data-act="finalize">Finalizar</button>
            <button type="button" class="btn btn-danger" data-act="revoke">Revocar</button>`;
  }
  return "";
}

async function openDetail(id) {
  const [r, trail] = await Promise.all([
    guarded(() => api.get(`/requests/${id}`)),
    api.get("/audit", { entity: "authorization_request", entity_id: String(id), limit: 100 }).catch(() => null),
  ]);
  if (!r) return;
  current = r;
  $("#d-eyebrow").innerHTML = `Solicitud #${r.id} · ${badge(r.status)}`;
  $("#d-title").textContent = r.engineer.full_name;
  $("#d-body").innerHTML = detailHtml(r, trail?.items);
  $("#d-actions").innerHTML = detailActions(r);
  drawerBg.hidden = false;
  drawer.setAttribute("aria-hidden", "false");
  drawer.classList.add("open");
  $("#d-close").focus();
}
$("#d-actions").addEventListener("click", (e) => {
  const act = e.target.closest("[data-act]")?.dataset.act;
  if (act && current) decide(current.id, act);
});

// ----------------------------------------------------------------- decisión
const DECISIONS = {
  approve: { title: "Aprobar solicitud", btn: "Aprobar", cls: "btn-primary", label: "Notas (opcional)", required: false,
    text: "Se generará una autorización temporal vinculada al ingeniero y a su tarjeta RFID, válida solo dentro de la ventana aprobada. Quedarás registrado como responsable." },
  reject: { title: "Rechazar solicitud", btn: "Rechazar", cls: "btn-danger", label: "Motivo del rechazo", required: true,
    text: "La solicitud quedará RECHAZADA de forma definitiva. Quedarás registrado como responsable." },
  revoke: { title: "Revocar autorización", btn: "Revocar", cls: "btn-danger", label: "Motivo de la revocación", required: true,
    text: "La autorización dejará de permitir accesos de inmediato." },
  finalize: { title: "Finalizar autorización", btn: "Finalizar", cls: "btn-primary", label: "Notas (opcional)", required: false,
    text: "Da por terminado el trabajo: la autorización deja de permitir accesos." },
};
const decideModal = $("#decide-modal");
let pending = null;

function decide(id, act) {
  const d = DECISIONS[act];
  pending = { id, act };
  $("#x-title").textContent = `${d.title} #${id}`;
  $("#x-text").textContent = d.text;
  $("#x-label").textContent = d.label;
  const notes = $("#x-notes");
  notes.value = "";
  notes.required = d.required;
  notes.removeAttribute("aria-invalid");
  const submit = $("#x-submit");
  submit.textContent = d.btn;
  submit.className = `btn ${d.cls}`;
  $("#x-error").hidden = true;
  decideModal.showModal();
  notes.focus();
}

$("#decide-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const d = DECISIONS[pending.act];
  const notes = $("#x-notes").value.trim();
  const err = $("#x-error");
  if ((d.required || notes) && notes.length < 3) {
    err.textContent = d.required ? "Indica un motivo (mínimo 3 caracteres)." : "Las notas deben tener al menos 3 caracteres.";
    err.hidden = false;
    $("#x-notes").setAttribute("aria-invalid", "true");
    return;
  }
  $("#x-submit").disabled = true;
  try {
    const r = await api.post(`/requests/${pending.id}/${pending.act}`, notes ? { notes } : {});
    decideModal.close();
    toast(`Solicitud #${r.id}: ${STATUS[r.status]?.label ?? r.status}`, "ok");
    await refresh();
    if (current?.id === r.id) openDetail(r.id);
  } catch (ex) {
    err.textContent = ex instanceof ApiError ? ex.message : String(ex);
    err.hidden = false;
    if (ex instanceof ApiError && ex.code === "REQUEST_WINDOW_PASSED") refresh();
  } finally {
    $("#x-submit").disabled = false;
  }
});

document.querySelectorAll("dialog [data-close]").forEach((b) => b.addEventListener("click", () => b.closest("dialog").close()));

// ----------------------------------------------------------------- nueva solicitud
const newModal = $("#new-modal");
const f = {
  eng: $("#n-eng"), uid: $("#n-uid"), area: $("#n-area"), reason: $("#n-reason"),
  date: $("#n-date"), start: $("#n-start"), end: $("#n-end"), duration: $("#n-duration"), obs: $("#n-obs"),
};
let engineer = null;
const pad = (n) => String(n).padStart(2, "0");
const toTime = (d) => `${pad(d.getHours())}:${pad(d.getMinutes())}`;
const toDate = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

function hint(el, text, kind = "") {
  el.textContent = text;
  el.className = `rq-hint ${kind}`;
}

async function loadAreas() {
  const areas = await guarded(() => api.get("/areas"));
  const list = Array.isArray(areas) ? areas : areas?.items ?? [];
  f.area.innerHTML = '<option value="">Selecciona un área…</option>' +
    list.map((a) => `<option value="${a.id}">${h(a.name)} (${h(a.code)})</option>`).join("");
}

async function lookupEngineer() {
  const code = f.eng.value.trim().toUpperCase();
  f.eng.value = code;
  engineer = null;
  f.uid.disabled = true;
  f.uid.innerHTML = '<option value="">Primero indica el ingeniero</option>';
  const eh = $("#n-eng-hint"), uh = $("#n-uid-hint");
  hint(uh, "Tarjeta activa vinculada al ingeniero.");
  if (!code) return hint(eh, "Debe estar registrado y activo.");
  if (!/^ENG-\d{4,6}$/.test(code)) return hint(eh, "Formato esperado: ENG-0001", "bad");
  const page = await guarded(() => api.get("/engineers", { q: code, limit: 20 }));
  const eng = page?.items?.find((x) => x.engineer_id === code);
  if (!eng) return hint(eh, "No existe ningún ingeniero con ese ID.", "bad");
  if (eng.status !== "ACTIVO") return hint(eh, `${eng.full_name}: ${eng.status}. No puede recibir autorizaciones.`, "bad");
  engineer = eng;
  hint(eh, `${eng.full_name} · ${eng.department}`, "ok");
  const cards = await guarded(() => api.get("/cards", { engineer_id: eng.id, limit: 50 }));
  const active = (cards?.items ?? []).filter((c) => c.status === "ACTIVA");
  if (!active.length) return hint(uh, "Este ingeniero no tiene ninguna tarjeta activa vinculada.", "bad");
  f.uid.innerHTML = active.map((c) => `<option value="${h(c.uid)}">${h(c.uid)}${c.label ? ` · ${h(c.label)}` : ""}</option>`).join("");
  f.uid.disabled = false;
  hint(uh, active.length > 1 ? `${active.length} tarjetas activas` : "Tarjeta vinculada verificada.", "ok");
}
f.eng.addEventListener("change", lookupEngineer);

function windowFromForm() {
  if (!f.date.value || !f.start.value) return null;
  const start = new Date(`${f.date.value}T${f.start.value}`);
  if (Number.isNaN(start.getTime())) return null;
  return start;
}
function syncFromEnd() {
  const start = windowFromForm();
  if (!start || !f.end.value) return;
  let end = new Date(`${f.date.value}T${f.end.value}`);
  if (end <= start) end = new Date(end.getTime() + 86_400_000); // termina al día siguiente
  f.duration.value = Math.round((end - start) / 60000);
  describeWindow();
}
function syncFromDuration() {
  const start = windowFromForm();
  const min = Number(f.duration.value);
  if (!start || !min) return;
  f.end.value = toTime(new Date(start.getTime() + min * 60000));
  describeWindow();
}
function describeWindow() {
  const start = windowFromForm(), min = Number(f.duration.value);
  const el = $("#n-window-hint");
  if (!start || !min) return hint(el, "Máximo 24 h. Si la hora de fin es anterior a la de inicio, termina al día siguiente.");
  if (min > 1440) return hint(el, "La duración máxima es de 24 h (1440 min).", "bad");
  const end = new Date(start.getTime() + min * 60000);
  hint(el, `Ventana: ${fmtDT(start.toISOString())} → ${fmtDT(end.toISOString())} (${fmtDuration(min)}).`,
    start.getTime() < Date.now() - 5 * 60000 ? "bad" : "ok");
}
f.start.addEventListener("change", () => (f.duration.value ? syncFromDuration() : syncFromEnd()));
f.date.addEventListener("change", () => (f.duration.value ? syncFromDuration() : syncFromEnd()));
f.end.addEventListener("change", syncFromEnd);
f.duration.addEventListener("input", syncFromDuration);

function openNew() {
  $("#new-form").reset();
  engineer = null;
  hint($("#n-eng-hint"), "Debe estar registrado y activo.");
  hint($("#n-uid-hint"), "Tarjeta activa vinculada al ingeniero.");
  f.uid.disabled = true;
  f.uid.innerHTML = '<option value="">Primero indica el ingeniero</option>';
  const start = new Date(Date.now() + 30 * 60000);
  start.setMinutes(Math.ceil(start.getMinutes() / 15) * 15, 0, 0);
  f.date.value = toDate(start);
  f.date.min = toDate(new Date());
  f.start.value = toTime(start);
  f.duration.value = 60;
  syncFromDuration();
  $("#n-error").hidden = true;
  newModal.showModal();
  f.eng.focus();
}
$("#new-btn").addEventListener("click", openNew);

function formError(msg) {
  const el = $("#n-error");
  el.innerHTML = msg;
  el.hidden = false;
  el.scrollIntoView({ block: "nearest" });
}

$("#new-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const problems = [];
  if (!engineer) problems.push("Indica un ingeniero registrado y activo.");
  if (!f.uid.value) problems.push("Selecciona la tarjeta RFID vinculada.");
  if (!f.area.value) problems.push("Selecciona el área del Data Center.");
  if (f.reason.value.trim().length < 5) problems.push("El motivo debe tener al menos 5 caracteres.");
  const start = windowFromForm(), min = Number(f.duration.value);
  if (!start) problems.push("Indica fecha y hora de inicio.");
  if (!Number.isInteger(min) || min < 1 || min > 1440) problems.push("La duración debe estar entre 1 y 1440 minutos.");
  if (problems.length) return formError(problems.map(h).join("<br>"));

  const end = new Date(start.getTime() + min * 60000);
  const body = {
    engineer_id: engineer.engineer_id,
    card_uid: f.uid.value,
    area_id: Number(f.area.value),
    reason: f.reason.value.trim(),
    start_at: start.toISOString(),
    end_at: end.toISOString(),
    duration_minutes: min,
    observations: f.obs.value.trim() || null,
  };
  $("#n-submit").disabled = true;
  try {
    const r = await api.post("/requests", body);
    newModal.close();
    toast(`Solicitud #${r.id} creada como pendiente`, "ok");
    document.querySelector('.rq-tabs [data-tab="PENDIENTE"]').click();
    await loadStats();
  } catch (ex) {
    if (ex instanceof ApiError && ex.details?.length) {
      formError(ex.details.map((d) => h(d.msg.replace(/^Value error, /, ""))).join("<br>"));
    } else {
      formError(h(ex.message ?? String(ex)));
    }
  } finally {
    $("#n-submit").disabled = false;
  }
});

// ----------------------------------------------------------------- arranque
await Promise.all([refresh(), isAdmin ? loadAreas() : null]);
const deepLink = Number(new URLSearchParams(location.search).get("id"));
if (deepLink) openDetail(deepLink);
setInterval(() => { if (!document.hidden && !document.querySelector("dialog[open]")) refresh(); }, 30_000);
