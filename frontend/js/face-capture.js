// Componente de captura facial para el registro de ingenieros (Registro 1).
//   const fc = new FaceCapture(rootEl, { min: 3, max: 5 });
//   rootEl.addEventListener("samples-change", (e) => e.detail.count);
//   const form = fc.formData(true);   // FormData con images[] + replace
//   fc.destroy();
// - Vista previa de la webcam con guía de encuadre y verificación de calidad en vivo
//   (POST /vision/quality, el servidor no guarda nada).
// - Captura manual o automática de varias muestras, o subida de fotografías.
// - Las muestras solo existen en memoria hasta enviarse; al destruir el componente se liberan.

import { api, ApiError, escapeHtml } from "/js/api.js";
import { captureJpeg, isActive, listCameras, startCamera, stopCamera } from "/js/camera.js";

const LIVE_INTERVAL_MS = 900;
const AUTO_SCORE = 0.7;
const AUTO_GAP_MS = 1400;

const ICON = {
  camera: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/></svg>',
  upload: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 16V4M7 9l5-5 5 5M4 20h16"/></svg>',
  shot: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/></svg>',
  stop: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="1"/></svg>',
  x: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>',
};

export class FaceCapture {
  constructor(root, { min = 3, max = 5 } = {}) {
    this.root = root;
    this.min = min;
    this.max = max;
    this.samples = []; // { id, blob, url, quality, source }
    this._seq = 0;
    this._timer = null;
    this._busy = false;
    this._lastAuto = 0;
    this._last = null;
    this._render();
  }

  // ------------------------------------------------------------------ public
  get count() { return this.samples.length; }
  get ready() { return this.samples.length >= this.min; }

  formData(replace = true) {
    const fd = new FormData();
    this.samples.forEach((s, i) => fd.append("images", s.blob, `muestra-${i + 1}.jpg`));
    fd.append("replace", String(replace));
    return fd;
  }

  clear() {
    this.samples.forEach((s) => URL.revokeObjectURL(s.url));
    this.samples = [];
    this._renderSamples();
  }

  destroy() {
    this.stop();
    this.clear();
  }

  stop() {
    clearInterval(this._timer);
    this._timer = null;
    stopCamera(this.$video);
    this.root.querySelector(".fc-stage").classList.remove("is-live");
    this._drawOverlay(null);
    this._setStatus("idle", "Cámara apagada");
    this._syncButtons();
  }

  // ------------------------------------------------------------------ render
  _render() {
    this.root.classList.add("fc");
    this.root.innerHTML = `
      <div class="fc-tabs" role="tablist" aria-label="Origen de las muestras">
        <button type="button" role="tab" aria-selected="true" data-tab="cam">${ICON.camera} Webcam</button>
        <button type="button" role="tab" aria-selected="false" data-tab="upload">${ICON.upload} Subir fotografía</button>
      </div>

      <div class="fc-pane" data-pane="cam">
        <div class="fc-stage">
          <video playsinline muted aria-label="Vista previa de la cámara"></video>
          <canvas class="fc-overlay" aria-hidden="true"></canvas>
          <div class="fc-guide" aria-hidden="true"></div>
          <div class="fc-placeholder">
            ${ICON.camera}
            <p>Activa la cámara y centra el rostro dentro de la guía.</p>
            <button type="button" class="btn btn-primary fc-start">Activar cámara</button>
          </div>
          <span class="fc-status" data-state="idle"><i></i><span>Cámara apagada</span></span>
          <span class="fc-rec" hidden>AUTO</span>
        </div>
        <div class="fc-feedback">
          <div class="fc-meter" aria-label="Calidad de la imagen"><div class="fc-meter-bar"></div></div>
          <ul class="fc-issues" aria-live="polite"><li class="muted">Las capturas se verifican automáticamente: un solo rostro, nítido, bien iluminado y de frente.</li></ul>
        </div>
        <div class="fc-controls">
          <button type="button" class="btn btn-primary fc-shot" disabled>${ICON.shot} Capturar muestra</button>
          <label class="fc-switch"><input type="checkbox" class="fc-auto"> Captura automática</label>
          <span class="spacer"></span>
          <select class="fc-device" aria-label="Cámara" hidden></select>
          <button type="button" class="btn btn-ghost fc-stop" disabled>${ICON.stop} Apagar</button>
        </div>
      </div>

      <div class="fc-pane" data-pane="upload" hidden>
        <label class="fc-drop">
          ${ICON.upload}
          <strong>Selecciona o arrastra fotografías faciales</strong>
          <span class="muted">JPEG, PNG o WebP · máx. 6 MB · un solo rostro de frente</span>
          <input type="file" class="fc-file" accept="image/jpeg,image/png,image/webp" multiple>
        </label>
      </div>

      <div class="fc-samples">
        <div class="fc-samples-head">
          <strong>Muestras capturadas</strong>
          <span class="fc-count"></span>
        </div>
        <div class="fc-thumbs"></div>
        <p class="fc-note muted">Las imágenes solo se usan para calcular la plantilla biométrica y se descartan: no se almacenan.</p>
      </div>`;

    this.$video = this.root.querySelector("video");
    this.$overlay = this.root.querySelector(".fc-overlay");
    this.root.querySelectorAll(".fc-tabs button").forEach((b) =>
      b.addEventListener("click", () => this._tab(b.dataset.tab)));
    this.root.querySelector(".fc-start").addEventListener("click", () => this._start());
    this.root.querySelector(".fc-stop").addEventListener("click", () => this.stop());
    this.root.querySelector(".fc-shot").addEventListener("click", () => this._shoot(false));
    this.root.querySelector(".fc-auto").addEventListener("change", (e) => {
      this.root.querySelector(".fc-rec").hidden = !e.target.checked;
    });
    this.root.querySelector(".fc-device").addEventListener("change", (e) => this._start(e.target.value));
    const file = this.root.querySelector(".fc-file");
    file.addEventListener("change", () => { this._addFiles(file.files); file.value = ""; });
    const drop = this.root.querySelector(".fc-drop");
    drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("is-over"); });
    drop.addEventListener("dragleave", () => drop.classList.remove("is-over"));
    drop.addEventListener("drop", (e) => {
      e.preventDefault();
      drop.classList.remove("is-over");
      this._addFiles(e.dataTransfer.files);
    });
    this._renderSamples();
  }

  _tab(name) {
    this.root.querySelectorAll(".fc-tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
    this.root.querySelectorAll(".fc-pane").forEach((p) => { p.hidden = p.dataset.pane !== name; });
    if (name !== "cam") this.stop();
  }

  _syncButtons() {
    const live = isActive(this.$video);
    const full = this.samples.length >= this.max;
    this.root.querySelector(".fc-shot").disabled = !live || full;
    this.root.querySelector(".fc-stop").disabled = !live;
  }

  _setStatus(state, text) {
    const el = this.root.querySelector(".fc-status");
    el.dataset.state = state;
    el.querySelector("span").textContent = text;
  }

  _emit() {
    this.root.dispatchEvent(new CustomEvent("samples-change", { detail: { count: this.samples.length, ready: this.ready } }));
  }

  // ------------------------------------------------------------------ camera
  async _start(deviceId) {
    const stage = this.root.querySelector(".fc-stage");
    this._setStatus("busy", "Abriendo cámara…");
    try {
      await startCamera(this.$video, { deviceId });
    } catch (err) {
      this._setStatus("bad", "Sin cámara");
      this._issues([err.message], "bad");
      return;
    }
    stage.classList.add("is-live");
    stage.style.aspectRatio = `${this.$video.videoWidth} / ${this.$video.videoHeight}`;
    this._setStatus("busy", "Analizando…");
    this._syncButtons();
    this._fillDevices();
    clearInterval(this._timer);
    this._timer = setInterval(() => this._liveCheck(), LIVE_INTERVAL_MS);
    this._liveCheck();
  }

  async _fillDevices() {
    const sel = this.root.querySelector(".fc-device");
    const cams = await listCameras().catch(() => []);
    if (cams.length < 2) { sel.hidden = true; return; }
    const current = this.$video.srcObject?.getVideoTracks()[0]?.getSettings().deviceId;
    sel.innerHTML = cams.map((c, i) =>
      `<option value="${escapeHtml(c.deviceId)}"${c.deviceId === current ? " selected" : ""}>${escapeHtml(c.label || `Cámara ${i + 1}`)}</option>`).join("");
    sel.hidden = false;
  }

  async _check(blob) {
    const fd = new FormData();
    fd.append("image", blob, "frame.jpg");
    return api.upload("/vision/quality", fd);
  }

  async _liveCheck() {
    if (this._busy || !isActive(this.$video) || document.hidden) return;
    this._busy = true;
    try {
      const blob = await captureJpeg(this.$video, { maxSide: 640, quality: 0.8 });
      const q = await this._check(blob);
      if (!isActive(this.$video)) return;
      this._last = q;
      this._showQuality(q);
      const auto = this.root.querySelector(".fc-auto").checked;
      if (auto && q.ok && q.score >= AUTO_SCORE && Date.now() - this._lastAuto > AUTO_GAP_MS
          && this.samples.length < this.max) {
        this._lastAuto = Date.now();
        this._busy = false;
        await this._shoot(true);
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) this.stop();
      else this._setStatus("bad", "Sin respuesta del servidor");
    } finally {
      this._busy = false;
    }
  }

  _showQuality(q) {
    const bar = this.root.querySelector(".fc-meter-bar");
    bar.style.width = `${Math.round((q.score ?? 0) * 100)}%`;
    bar.dataset.state = q.ok ? "ok" : q.face_count ? "warn" : "bad";
    if (q.ok) {
      this._setStatus("ok", `Rostro válido · calidad ${Math.round(q.score * 100)} %`);
      this._issues(["Encuadre correcto: puedes capturar."], "ok");
    } else {
      this._setStatus(q.face_count ? "warn" : "bad", q.face_count ? "Ajusta la posición" : "Sin rostro");
      this._issues(q.messages, "warn");
    }
    this._drawOverlay(q);
  }

  _issues(list, tone) {
    this.root.querySelector(".fc-issues").innerHTML =
      list.map((m) => `<li class="is-${tone}">${escapeHtml(m)}</li>`).join("");
  }

  _drawOverlay(q) {
    const c = this.$overlay;
    const w = this.$video.clientWidth;
    const h = this.$video.clientHeight;
    c.width = w;
    c.height = h;
    const ctx = c.getContext("2d");
    ctx.clearRect(0, 0, w, h);
    if (!q?.bbox || !q.image_width) return;
    const sx = w / q.image_width;
    const sy = h / q.image_height;
    const [x1, y1, x2, y2] = q.bbox;
    const color = getComputedStyle(this.root).getPropertyValue(q.ok ? "--ok" : "--warn").trim() || "#4cc286";
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    // Preview is mirrored: mirror the box too.
    const left = w - x2 * sx;
    const top = y1 * sy;
    const bw = (x2 - x1) * sx;
    const bh = (y2 - y1) * sy;
    const k = Math.min(bw, bh) * 0.22;
    ctx.beginPath();
    for (const [px, py, dx, dy] of [[left, top, 1, 1], [left + bw, top, -1, 1], [left, top + bh, 1, -1], [left + bw, top + bh, -1, -1]]) {
      ctx.moveTo(px + dx * k, py);
      ctx.lineTo(px, py);
      ctx.lineTo(px, py + dy * k);
    }
    ctx.stroke();
  }

  async _shoot(auto) {
    if (this.samples.length >= this.max || !isActive(this.$video)) return;
    const btn = this.root.querySelector(".fc-shot");
    btn.disabled = true;
    try {
      const blob = await captureJpeg(this.$video);
      const q = await this._check(blob);
      if (!q.ok) {
        if (!auto) this._issues(["Captura descartada:", ...q.messages], "warn");
        return;
      }
      this.root.querySelector(".fc-stage").classList.add("flash");
      setTimeout(() => this.root.querySelector(".fc-stage")?.classList.remove("flash"), 180);
      this._add(blob, q, "Webcam");
    } catch (err) {
      this._issues([err.message ?? String(err)], "bad");
    } finally {
      this._syncButtons();
    }
  }

  async _addFiles(fileList) {
    const files = [...fileList];
    const box = this.root.querySelector(".fc-drop");
    for (const file of files) {
      if (this.samples.length >= this.max) {
        this._issues([`Máximo ${this.max} muestras.`], "warn");
        break;
      }
      box.classList.add("is-busy");
      try {
        const q = await this._check(file);
        if (!q.ok) {
          this._issues([`${file.name}: ${q.messages.join("; ")}`], "warn");
          continue;
        }
        this._add(file, q, "Fotografía");
      } catch (err) {
        this._issues([`${file.name}: ${err.message}`], "bad");
      } finally {
        box.classList.remove("is-busy");
      }
    }
  }

  _add(blob, quality, source) {
    this.samples.push({ id: ++this._seq, blob, url: URL.createObjectURL(blob), quality, source });
    this._renderSamples();
    if (this.samples.length >= this.max) {
      this.root.querySelector(".fc-auto").checked = false;
      this.root.querySelector(".fc-rec").hidden = true;
    }
  }

  _remove(id) {
    const s = this.samples.find((x) => x.id === id);
    if (s) URL.revokeObjectURL(s.url);
    this.samples = this.samples.filter((x) => x.id !== id);
    this._renderSamples();
  }

  _renderSamples() {
    const n = this.samples.length;
    const count = this.root.querySelector(".fc-count");
    count.textContent = `${n} / ${this.max} · mínimo ${this.min}`;
    count.dataset.state = n >= this.min ? "ok" : "pending";
    const thumbs = this.root.querySelector(".fc-thumbs");
    const slots = [];
    this.samples.forEach((s, i) => {
      slots.push(`
        <figure class="fc-thumb">
          <img src="${s.url}" alt="Muestra ${i + 1}">
          <figcaption><span>${escapeHtml(s.source)}</span><b>${Math.round(s.quality.score * 100)}%</b></figcaption>
          <button type="button" class="fc-del" data-id="${s.id}" aria-label="Quitar muestra ${i + 1}">${ICON.x}</button>
        </figure>`);
    });
    for (let i = n; i < this.max; i++) {
      slots.push(`<div class="fc-slot${i < this.min ? " is-required" : ""}"><span>${i + 1}</span></div>`);
    }
    thumbs.innerHTML = slots.join("");
    thumbs.querySelectorAll(".fc-del").forEach((b) => b.addEventListener("click", () => this._remove(Number(b.dataset.id))));
    this._syncButtons();
    this._emit();
  }
}
