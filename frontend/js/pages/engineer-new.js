import { ready } from "/js/layout.js";
import { api, ApiError, guarded, toast } from "/js/api.js";
import { FaceCapture } from "/js/face-capture.js";

const admin = await ready;
const $ = (id) => document.getElementById(id);

if (admin.role !== "admin") {
  $("auditor-note").hidden = false;
} else {
  init();
}

function init() {
  const form = $("form");
  const capture = new FaceCapture($("capture"), { min: 3, max: 5 });
  window.addEventListener("pagehide", () => capture.destroy());

  guarded(async () => { $("next-id").textContent = (await api.get("/engineers/next-id")).engineer_id; });

  const updateSubmit = () => {
    const skip = $("skip-face").checked;
    $("submit").textContent = skip || capture.ready ? "Registrar ingeniero" : `Faltan ${3 - capture.count} muestras faciales`;
    $("submit").disabled = !(skip || capture.ready);
  };
  $("capture").addEventListener("samples-change", updateSubmit);
  $("skip-face").addEventListener("change", updateSubmit);
  updateSubmit();

  form.querySelectorAll("input[name]").forEach((el) => el.addEventListener("input", () => fieldError(el.name, "")));

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (!validate(form)) return;
    const data = Object.fromEntries(new FormData(form));
    const body = {
      full_name: data.full_name.trim(),
      department: data.department.trim(),
      position: data.position.trim(),
      institutional_email: data.institutional_email.trim(),
      status: data.status,
    };
    $("submit").disabled = true;
    const steps = progress();
    let eng;
    steps.set("data", "busy", "Guardando datos personales…");
    try {
      eng = await api.post("/engineers", body);
      steps.set("data", "ok", `Ingeniero ${eng.engineer_id} registrado`);
    } catch (err) {
      steps.set("data", "bad", err.message);
      showApiErrors(err);
      $("submit").disabled = false;
      return;
    }
    if ($("skip-face").checked || !capture.count) {
      capture.destroy();
      toast(`${eng.engineer_id} registrado sin rostro`, "info");
      location.href = `/pages/engineer.html?id=${eng.id}&created=1`;
      return;
    }
    steps.set("face", "busy", "Procesando muestras faciales (detección, calidad, plantilla y duplicados)…");
    try {
      const res = await api.upload(`/engineers/${eng.id}/face`, capture.formData(true));
      steps.set("face", "ok", `${res.samples_total} muestras biométricas almacenadas de forma cifrada`);
      capture.destroy();
      toast(`${eng.engineer_id} registrado con su rostro`, "ok");
      location.href = `/pages/engineer.html?id=${eng.id}&created=1`;
    } catch (err) {
      const detail = err instanceof ApiError && Array.isArray(err.details)
        ? err.details.filter((d) => !d.accepted).map((d) => `Muestra ${d.index + 1}: ${d.error}`).join(" · ") : "";
      steps.set("face", "bad", `${err.message}${detail ? ` — ${detail}` : ""}`);
      steps.note(`El ingeniero quedó registrado sin rostro. <a href="/pages/engineer.html?id=${eng.id}">Abrir su ficha</a> para repetir la captura.`);
    }
  });
}

function validate(form) {
  let ok = true;
  for (const el of form.querySelectorAll("input[name]:not([type=radio])")) {
    el.value = el.value.trim();
    let msg = "";
    if (el.validity.valueMissing) msg = "Campo obligatorio";
    else if (el.validity.tooShort) msg = `Mínimo ${el.minLength} caracteres`;
    else if (el.validity.typeMismatch) msg = "Correo no válido";
    fieldError(el.name, msg);
    if (msg) ok = false;
  }
  if (!ok) form.querySelector('[aria-invalid="true"]')?.focus();
  return ok;
}

function fieldError(name, msg) {
  const input = document.querySelector(`input[name="${name}"]`);
  const box = document.querySelector(`.en-field-error[data-for="${name}"]`);
  if (input) input.setAttribute("aria-invalid", msg ? "true" : "false");
  if (box) box.textContent = msg;
}

function showApiErrors(err) {
  if (!(err instanceof ApiError)) return;
  if (err.code === "EMAIL_TAKEN" || err.code === "EMAIL_NOT_INSTITUTIONAL") {
    fieldError("institutional_email", err.message);
  } else if (err.code === "VALIDATION_ERROR" && Array.isArray(err.details)) {
    for (const d of err.details) fieldError(d.loc?.at(-1), d.msg);
  }
}

function progress() {
  const list = $("progress");
  list.hidden = false;
  list.innerHTML = "";
  const items = {};
  return {
    set(key, state, text) {
      if (!items[key]) { items[key] = document.createElement("li"); list.appendChild(items[key]); }
      const icon = { ok: "✓", bad: "✕", busy: "…" }[state] ?? "·";
      items[key].dataset.state = state;
      items[key].textContent = `${icon} ${text}`;
    },
    note(html) {
      const li = document.createElement("li");
      li.innerHTML = html; // contenido propio, sin datos del servidor salvo el id numérico
      list.appendChild(li);
    },
  };
}

