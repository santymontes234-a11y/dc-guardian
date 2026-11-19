import { ready } from "/js/layout.js";
import { api, ApiError, escapeHtml, fmtDate, guarded, toast } from "/js/api.js";
import { FaceCapture } from "/js/face-capture.js";
import { fmtDay, initials, statusBadge } from "/js/pages/engineers-common.js";
import { credentialBlob, drawCredential } from "/js/qr-credential.js";

const admin = await ready;
const isAdmin = admin.role === "admin";
const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const id = Number(params.get("id"));
let eng = null;
let profile = null;
let qr = null;          // estado GET /engineers/{id}/qr
let issued = null;      // { canvas, qrText } solo mientras el diálogo de emisión está abierto

const CARD_TONE = { ACTIVA: "ok", BLOQUEADA: "warn", PERDIDA: "danger", BAJA: "muted" };

if (!Number.isInteger(id) || id < 1) {
  $("eng-name").textContent = "Ingeniero no especificado";
} else {
  if (params.get("created")) toast("Registro completado. Recuerda: el acceso requiere una solicitud aprobada.", "ok");
  await reload();
}

async function reload() {
  const [e, p] = await Promise.all([
    guarded(() => api.get(`/engineers/${id}`)),
    guarded(() => api.get(`/engineers/${id}/face`)),
  ]);
  if (!e) { $("eng-name").textContent = "Ingeniero no encontrado"; return; }
  eng = e;
  profile = p;
  render();
  await loadQr();
}

// ------------------------------------------------------------------ render
function render() {
  const erased = eng.status === "ELIMINADO";
  document.title = `${eng.engineer_id} · DC Guardian`;
  $("avatar").innerHTML = initials(eng.full_name);
  $("eng-code").textContent = eng.engineer_id;
  $("eng-name").textContent = eng.full_name;
  $("eng-meta").innerHTML = `${statusBadge(eng.status)}
    <span class="muted">${escapeHtml(eng.position)} · ${escapeHtml(eng.department)}</span>`;
  $("requests-link").href = `/pages/requests.html?engineer_id=${eng.id}`;

  $("data").innerHTML = [
    ["ID de ingeniero", `<span class="en-code">${escapeHtml(eng.engineer_id)}</span>`],
    ["Nombre completo", escapeHtml(eng.full_name)],
    ["Departamento", escapeHtml(eng.department)],
    ["Cargo", escapeHtml(eng.position)],
    ["Correo institucional", erased ? '<span class="muted">Eliminado</span>' : `<a href="mailto:${escapeHtml(eng.institutional_email)}">${escapeHtml(eng.institutional_email)}</a>`],
    ["Estado", statusBadge(eng.status)],
    ["Fecha de registro", fmtDate(eng.registration_date)],
    ["Última modificación", fmtDate(eng.updated_at)],
  ].map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");

  renderActions(erased);
  renderFace(erased);
  renderCards();
  $("edit-btn").hidden = erased;
  $("danger").hidden = erased || !isAdmin;
  $("del-face-btn").disabled = !eng.has_face;
}

function renderActions(erased) {
  const box = $("actions");
  if (erased) { box.innerHTML = ""; return; }
  const btns = [];
  if (eng.status !== "ACTIVO") btns.push(`<button type="button" class="btn btn-primary" data-status="ACTIVO">Activar</button>`);
  if (eng.status !== "SUSPENDIDO") btns.push(`<button type="button" class="btn btn-danger" data-status="SUSPENDIDO">Suspender</button>`);
  if (eng.status !== "INACTIVO") btns.push(`<button type="button" class="btn" data-status="INACTIVO">Desactivar</button>`);
  box.innerHTML = btns.join("");
  box.querySelectorAll("[data-status]").forEach((b) => b.addEventListener("click", () => openStatus(b.dataset.status)));
}

function renderFace(erased) {
  const box = $("face");
  $("face-btn").hidden = erased;
  $("face-btn").textContent = eng.has_face ? "Volver a registrar" : "Registrar rostro";
  if (!eng.has_face || !profile) {
    box.innerHTML = `<p class="muted" style="margin:0">${erased ? "Datos biométricos eliminados."
      : "Sin plantilla facial. Sin ella el ingeniero no podrá superar la verificación facial en la puerta."}</p>`;
    return;
  }
  const rows = profile.samples.map((s, i) => `
    <tr>
      <td>${i + 1}${s.is_primary ? ' <span class="badge badge-info">Principal</span>' : ""}</td>
      <td><span class="en-quality"><span class="bar"><i style="width:${Math.round((s.quality_score ?? 0) * 100)}%"></i></span>${Math.round((s.quality_score ?? 0) * 100)}%</span></td>
      <td class="muted">${fmtDay(s.created_at)}</td>
      <td class="admin-only"><button type="button" class="btn btn-ghost" data-del="${s.id}" aria-label="Eliminar muestra ${i + 1}">Eliminar</button></td>
    </tr>`).join("");
  box.innerHTML = `
    <dl class="en-dl" style="margin-bottom:12px">
      <dt>Referencia biométrica</dt><dd><span class="en-ref">${escapeHtml(profile.face_embedding_reference)}</span></dd>
      <dt>Muestras</dt><dd>${profile.samples.length} de ${profile.max_samples} (mínimo ${profile.min_samples})</dd>
      <dt>Modelo</dt><dd class="mono">${escapeHtml([...new Set(profile.samples.map((s) => s.model_name))].join(", "))}</dd>
      <dt>Almacenamiento</dt><dd>Plantillas cifradas, sin imágenes</dd>
    </dl>
    <div class="table-wrap"><table class="table en-samples">
      <thead><tr><th>#</th><th>Calidad</th><th>Fecha</th><th class="admin-only"></th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
  box.querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", () => deleteSample(Number(b.dataset.del))));
}

function renderCards() {
  $("cards").innerHTML = eng.cards.length
    ? `<div class="table-wrap"><table class="table"><thead><tr><th>UID</th><th>Etiqueta</th><th>Estado</th></tr></thead><tbody>${
      eng.cards.map((c) => `<tr><td class="mono">${escapeHtml(c.uid)}</td><td>${escapeHtml(c.label ?? "—")}</td>
        <td><span class="badge badge-${CARD_TONE[c.status] ?? "muted"}">${escapeHtml(c.status)}</span></td></tr>`).join("")
    }</tbody></table></div>`
    : '<p class="muted" style="margin:0">Sin tarjetas vinculadas.</p>';
}

// ------------------------------------------------------------------ edición
$("edit-btn").addEventListener("click", () => {
  const f = $("edit-form");
  for (const k of ["full_name", "department", "position", "institutional_email"]) f.elements[k].value = eng[k];
  $("edit-error").textContent = "";
  f.hidden = false;
  $("data").hidden = true;
  $("edit-btn").hidden = true;
  f.elements.full_name.focus();
});
$("edit-cancel").addEventListener("click", closeEdit);

function closeEdit() {
  $("edit-form").hidden = true;
  $("data").hidden = false;
  $("edit-btn").hidden = false;
}

$("edit-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target;
  if (!f.reportValidity()) return;
  const changes = {};
  for (const k of ["full_name", "department", "position", "institutional_email"]) {
    const v = f.elements[k].value.trim();
    if (v !== eng[k]) changes[k] = v;
  }
  if (!Object.keys(changes).length) { closeEdit(); return; }
  try {
    eng = await api.patch(`/engineers/${id}`, changes);
    toast("Datos actualizados", "ok");
    closeEdit();
    render();
  } catch (err) {
    $("edit-error").textContent = err.message;
  }
});

// ------------------------------------------------------------------ estado
const STATUS_TEXT = {
  ACTIVO: ["Activar ingeniero", "Podrá volver a recibir autorizaciones. Las solicitudes revocadas no se reactivan."],
  SUSPENDIDO: ["Suspender ingeniero", "Se revocarán sus autorizaciones aprobadas y se rechazarán las pendientes de inmediato."],
  INACTIVO: ["Desactivar ingeniero", "Se revocarán sus autorizaciones aprobadas y se rechazarán las pendientes."],
};
let pendingStatus = null;

function openStatus(status) {
  pendingStatus = status;
  const [title, desc] = STATUS_TEXT[status];
  $("status-title").textContent = `${title} ${eng.engineer_id}`;
  $("status-desc").textContent = desc;
  $("status-ok").className = `btn ${status === "ACTIVO" ? "btn-primary" : "btn-danger"}`;
  $("status-form").reset();
  $("status-dlg").showModal();
}

$("status-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const reason = ev.target.elements.reason.value.trim();
  if (reason.length < 3) { ev.target.elements.reason.reportValidity(); return; }
  const res = await guarded(() => api.post(`/engineers/${id}/status`, { status: pendingStatus, reason }));
  if (!res) return;
  $("status-dlg").close();
  const closed = res.requests_revoked + res.requests_rejected;
  toast(`Estado: ${res.engineer.status}${closed ? ` · ${res.requests_revoked} revocadas, ${res.requests_rejected} rechazadas` : ""}`, "ok");
  eng = res.engineer;
  render();
});

document.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => b.closest("dialog").close()));

// ------------------------------------------------------------------ biometría
let capture = null;

$("face-btn").addEventListener("click", () => {
  $("face-desc").textContent = eng.has_face
    ? "Captura nuevas muestras. Por defecto reemplazan a las actuales y se genera una nueva referencia biométrica."
    : "Captura entre 3 y 5 muestras del rostro del ingeniero.";
  $("append-wrap").hidden = !eng.has_face;
  $("face-append").checked = false;
  $("face-progress").innerHTML = "";
  capture?.destroy();
  capture = new FaceCapture($("face-capture"), { min: profile?.min_samples ?? 3, max: profile?.max_samples ?? 5 });
  syncSave();
  $("face-dlg").showModal();
});

$("face-capture").addEventListener("samples-change", syncSave);
$("face-append").addEventListener("change", syncSave);

function syncSave() {
  const append = $("face-append").checked;
  const existing = append ? eng.face_samples : 0;
  const min = profile?.min_samples ?? 3;
  $("face-save").disabled = !capture || capture.count === 0 || existing + capture.count < min;
}

function closeFace() {
  capture?.destroy();
  capture = null;
  $("face-dlg").close();
}
$("face-cancel").addEventListener("click", closeFace);
$("face-dlg").addEventListener("cancel", () => { capture?.destroy(); capture = null; });

$("face-save").addEventListener("click", async () => {
  const btn = $("face-save");
  btn.disabled = true;
  $("face-progress").innerHTML = '<li data-state="busy">… Procesando muestras</li>';
  try {
    const res = await api.upload(`/engineers/${id}/face`, capture.formData(!$("face-append").checked));
    toast(`${res.samples_added} muestras registradas (${res.samples_total} en total)`, "ok");
    closeFace();
    await reload();
  } catch (err) {
    const lines = [`<li data-state="bad">✕ ${escapeHtml(err.message)}</li>`];
    if (err instanceof ApiError && Array.isArray(err.details)) {
      for (const d of err.details.filter((x) => !x.accepted)) {
        lines.push(`<li data-state="bad">Muestra ${d.index + 1}: ${escapeHtml(d.error ?? "")}</li>`);
      }
    }
    $("face-progress").innerHTML = lines.join("");
    btn.disabled = false;
  }
});

async function deleteSample(sampleId) {
  if (!confirm("¿Eliminar esta muestra facial? Esta acción no se puede deshacer.")) return;
  const res = await guarded(() => api.del(`/engineers/${id}/face/${sampleId}`));
  if (res) { toast("Muestra eliminada", "ok"); await reload(); }
}

$("del-face-btn").addEventListener("click", async () => {
  if (!confirm(`¿Eliminar TODAS las muestras biométricas de ${eng.engineer_id}? Los datos personales se conservan.`)) return;
  const res = await guarded(() => api.del(`/engineers/${id}/face`));
  if (res) { toast("Datos biométricos eliminados", "ok"); await reload(); }
});

// ------------------------------------------------------------------ borrado total
$("erase-btn").addEventListener("click", () => {
  $("erase-code").textContent = eng.engineer_id;
  $("erase-form").reset();
  $("erase-ok").disabled = true;
  $("erase-dlg").showModal();
});

$("erase-form").addEventListener("input", (ev) => {
  const f = ev.currentTarget;
  $("erase-ok").disabled = f.elements.confirm.value.trim().toUpperCase() !== eng.engineer_id
    || f.elements.reason.value.trim().length < 3;
});

$("erase-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target;
  const res = await guarded(() => api.post(`/engineers/${id}/erase`, {
    confirm_engineer_id: f.elements.confirm.value.trim().toUpperCase(),
    reason: f.elements.reason.value.trim(),
  }));
  if (!res) return;
  $("erase-dlg").close();
  toast(`Datos de ${res.engineer.engineer_id} eliminados · ${res.face_samples_deleted} muestras, ${res.cards_unlinked} tarjetas desvinculadas`, "ok");
  eng = res.engineer;
  profile = null;
  render();
});

// ------------------------------------------------------------------ credencial QR

async function loadQr() {
  try {
    qr = await api.get(`/engineers/${id}/qr`);
  } catch (err) {
    qr = null;
    if (err instanceof ApiError && err.status === 404) qr = { active: false };
    else if (err instanceof ApiError && err.status === 403) {
      $("qr-status").innerHTML = '<p class="muted" style="margin:0">Solo los administradores pueden consultar la credencial QR.</p>';
      $("qr-issue").hidden = true;
      $("qr-revoke").hidden = true;
      return;
    } else if (!(err instanceof ApiError && err.status === 401)) {
      $("qr-status").innerHTML = `<p class="muted" style="margin:0">No se pudo consultar la credencial: ${escapeHtml(err.message)}</p>`;
      return;
    }
  }
  renderQr();
}

function renderQr() {
  const erased = eng?.status === "ELIMINADO";
  const active = Boolean(qr?.active);
  $("qr-issue").hidden = erased || !isAdmin;
  $("qr-options").hidden = erased || !isAdmin;
  $("qr-issue").textContent = active ? "Generar nuevo QR" : "Generar QR";
  $("qr-revoke").hidden = !active || !isAdmin;
  if (!qr) return;
  const rows = [["Estado", active ? '<span class="badge badge-ok">Activa</span>'
    : '<span class="badge badge-muted">Sin credencial activa</span>']];
  if (qr.prefix) rows.push(["Prefijo", `<span class="mono">${escapeHtml(qr.prefix)}</span>`]);
  if (active || qr.created_at) rows.push(["Emitida", fmtDate(qr.created_at)]);
  if (active) {
    const kind = qr.single_use ? "Pase de un solo uso" : qr.expires_at ? "Pase temporal" : "Permanente";
    rows.push(["Tipo", kind]);
    const expiry = qr.expires_at ? fmtDate(qr.expires_at) : "Sin vencimiento";
    rows.push(["Vence", qr.expired ? `${expiry} <span class="badge badge-muted">Vencida</span>` : expiry]);
  }
  if (active || qr.last_used_at) rows.push(["Último uso", qr.last_used_at ? fmtDate(qr.last_used_at) : "Nunca"]);
  $("qr-status").innerHTML = `<dl class="qr-dl">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>`;
}

$("qr-kind").addEventListener("change", () => {
  const temporary = Boolean($("qr-kind").value);
  $("qr-single").disabled = !temporary;  // un pase permanente de un solo uso no existe
  if (!temporary) $("qr-single").checked = false;
});

$("qr-issue").addEventListener("click", async () => {
  if (qr?.active && !confirm(`${eng.engineer_id} ya tiene una credencial QR activa (prefijo ${qr.prefix ?? "?"}). `
    + "Al generar una nueva, la anterior queda revocada. ¿Continuar?")) return;
  const btn = $("qr-issue");
  btn.disabled = true;
  try {
    const minutes = Number($("qr-kind").value);
    const body = {};
    if (minutes > 0) {
      body.valid_minutes = minutes;
      if ($("qr-single").checked) body.single_use = true;
    }
    const r = await api.post(`/engineers/${id}/qr`, body);
    if (!r?.qr_text) throw new Error("El servidor no devolvió el código");
    const canvas = drawCredential({
      qrText: r.qr_text,
      name: r.engineer?.full_name ?? eng.full_name,
      position: r.engineer?.position ?? eng.position,
      engineerCode: eng.engineer_id,
      prefix: r.prefix,
      issuedAt: new Date().toISOString(),
      expiresAt: r.expires_at,
      singleUse: r.single_use,
    });
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", `Credencial QR de ${r.engineer?.full_name ?? eng.full_name}, prefijo ${r.prefix ?? ""}`);
    issued = { canvas, qrText: r.qr_text };
    $("qr-preview").replaceChildren(canvas);
    $("qr-dlg").showModal();
    toast("Credencial QR emitida", "ok");
  } catch (err) {
    if (!(err instanceof ApiError && err.status === 401)) toast(err.message ?? String(err), "error");
  } finally {
    btn.disabled = false;
    await loadQr();
  }
});

function forgetIssued() {
  // El texto completo no se conserva en la página después de cerrar el diálogo.
  issued = null;
  $("qr-preview").replaceChildren();
  $("cred-print").replaceChildren();
}
$("qr-close").addEventListener("click", () => $("qr-dlg").close());
$("qr-dlg").addEventListener("close", forgetIssued);
$("qr-dlg").addEventListener("cancel", (ev) => {
  if (!confirm("El código no se podrá volver a ver. ¿Cerrar de todos modos?")) ev.preventDefault();
});

$("qr-png").addEventListener("click", async () => {
  if (!issued) return;
  try {
    const url = URL.createObjectURL(await credentialBlob(issued.canvas));
    const a = document.createElement("a");
    a.href = url;
    a.download = `credencial-qr-${eng.engineer_id}.png`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  } catch (err) { toast(err.message, "error"); }
});

$("qr-print").addEventListener("click", () => {
  if (!issued) return;
  const img = new Image();
  img.alt = "Credencial QR";
  img.src = issued.canvas.toDataURL("image/png");
  $("cred-print").replaceChildren(img);
  document.body.classList.add("print-credential");
  const done = () => {
    document.body.classList.remove("print-credential");
    $("cred-print").replaceChildren();
  };
  window.addEventListener("afterprint", done, { once: true });
  img.decode().catch(() => {}).finally(() => window.print());
});

$("qr-copy").addEventListener("click", async () => {
  if (!issued) return;
  try {
    await navigator.clipboard.writeText(issued.qrText);
    toast("Texto del QR copiado: pégalo en la entrada manual del lector QR", "ok");
  } catch {
    toast("El navegador no permite copiar (requiere HTTPS o localhost)", "error");
  }
});

$("qr-revoke").addEventListener("click", async () => {
  if (!confirm(`¿Revocar la credencial QR de ${eng.engineer_id} (prefijo ${qr?.prefix ?? "?"})? `
    + "Dejará de abrir la entrada principal de inmediato.")) return;
  try {
    await api.del(`/engineers/${id}/qr`);
    toast("Credencial QR revocada", "ok");
  } catch (err) {
    if (!(err instanceof ApiError && err.status === 401)) toast(err.message, "error");
  }
  await loadQr();
});
