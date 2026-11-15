import { ready } from "/js/layout.js";
import { api, escapeHtml, fmtDate, guarded, toast } from "/js/api.js";
import { $, badge, emptyRow } from "/js/ui.js";

await ready;

const TONE = { ACTIVA: "ok", BLOQUEADA: "warn", PERDIDA: "danger", BAJA: "muted" };
let engineers = [];

async function loadEngineers() {
  const page = await guarded(() => api.get("/engineers", { status: "ACTIVO", limit: 200 }));
  engineers = page?.items ?? [];
  $("engineer-select").innerHTML = '<option value="">— sin asignar —</option>' + engineers.map((e) =>
    `<option value="${e.id}">${escapeHtml(e.engineer_id)} · ${escapeHtml(e.full_name)}</option>`).join("");
}

async function load() {
  const page = await guarded(() => api.get("/cards", { q: $("q").value.trim(), status: $("status").value, limit: 200 }));
  if (!page) return;
  $("rows").innerHTML = page.items.map((c) => {
    const locked = c.locked_until && new Date(c.locked_until) > new Date();
    return `<tr data-id="${c.id}">
      <td class="mono">${escapeHtml(c.uid)}</td>
      <td>${escapeHtml(c.label ?? "—")}</td>
      <td>${c.engineer ? `${escapeHtml(c.engineer.full_name)} <span class="muted mono">${escapeHtml(c.engineer.engineer_id)}</span>` : '<span class="muted">sin asignar</span>'}</td>
      <td>${badge(c.status, TONE[c.status])}</td>
      <td>${c.failed_attempts}</td>
      <td>${locked ? badge(`hasta ${fmtDate(c.locked_until)}`, "danger") : "—"}</td>
      <td class="row admin-only">
        ${["PERDIDA", "BAJA"].includes(c.status) ? "" : '<button class="btn" data-act="assign">Vincular</button>'}
        ${c.status === "ACTIVA" ? '<button class="btn" data-act="block">Bloquear</button>' : ""}
        ${c.status === "BLOQUEADA" ? '<button class="btn" data-act="activate">Activar</button>' : ""}
        ${["ACTIVA", "BLOQUEADA"].includes(c.status) ? '<button class="btn btn-danger" data-act="lost">Perdida</button>' : ""}
        ${c.status !== "BAJA" ? '<button class="btn btn-danger" data-act="retire">Baja</button>' : ""}
        ${locked ? '<button class="btn" data-act="unlock">Desbloquear</button>' : ""}
      </td></tr>`;
  }).join("") || emptyRow(7, "No hay tarjetas");
}

function ask(title, inner) {
  return new Promise((resolve) => {
    const dlg = $("dlg");
    $("dlg-form").innerHTML = `<h2 style="margin:0">${title}</h2>${inner}
      <div class="row"><span class="spacer"></span><button class="btn" value="cancel">Cancelar</button>
      <button class="btn btn-primary" value="ok">Confirmar</button></div>`;
    dlg.onclose = () => resolve(dlg.returnValue === "ok" ? new FormData($("dlg-form")) : null);
    dlg.showModal();
  });
}

const STATUS_FOR = { block: "BLOQUEADA", activate: "ACTIVA", lost: "PERDIDA", retire: "BAJA" };

$("rows").addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  const id = btn.closest("tr").dataset.id;
  const act = btn.dataset.act;
  if (act === "assign") {
    const form = await ask("Vincular tarjeta", `<label>Ingeniero <select name="engineer_id">
      <option value="">— desvincular —</option>${engineers.map((x) => `<option value="${x.id}">${escapeHtml(x.engineer_id)} · ${escapeHtml(x.full_name)}</option>`).join("")}
      </select></label>`);
    if (!form) return;
    const engineer_id = form.get("engineer_id") ? Number(form.get("engineer_id")) : null;
    if (await guarded(() => api.post(`/cards/${id}/assign`, { engineer_id }))) toast("Vinculación actualizada", "ok");
  } else if (act === "unlock") {
    if (await guarded(() => api.post(`/cards/${id}/unlock`))) toast("Tarjeta desbloqueada", "ok");
  } else {
    const status = STATUS_FOR[act];
    const warn = ["PERDIDA", "BAJA"].includes(status)
      ? '<p class="muted" style="margin:0">Se revocarán las autorizaciones abiertas de esta tarjeta.</p>' : "";
    const form = await ask(`Cambiar a ${status}`, `${warn}<label>Motivo <input name="reason" required minlength="3" maxlength="300"></label>`);
    if (!form) return;
    const r = await guarded(() => api.post(`/cards/${id}/status`, { status, reason: form.get("reason") }));
    if (r) toast(`Tarjeta ${status}${r.requests_revoked ? ` · ${r.requests_revoked} autorizaciones revocadas` : ""}`, "ok");
  }
  load();
});

$("create").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  const body = { uid: form.get("uid"), label: form.get("label") || null,
    engineer_id: form.get("engineer_id") ? Number(form.get("engineer_id")) : null };
  if (await guarded(() => api.post("/cards", body))) {
    toast("Tarjeta registrada", "ok");
    e.target.reset();
    load();
  }
});

let t = null;
$("q").addEventListener("input", () => { clearTimeout(t); t = setTimeout(load, 250); });
$("status").addEventListener("change", load);

await loadEngineers();
await load();
