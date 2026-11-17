// Generador de la presentación de DC Guardian (pptxgenjs). Las animaciones se inyectan después (animate.py).
const path = require("path");
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa");
const md = require("react-icons/md");
const { applyTheme } = require(process.env.SKILL_DIR + "/scripts/apply_theme.js");

const ROOT = process.env.ROOT;
const OUT = process.argv[2];
const CAP = (f) => path.join(ROOT, "entregables/capturas", f);

const HEX = {
  navy: "0B1B33", ink: "1C2430", blue: "1F5FBF", cyan: "2BB3C0", green: "1D7A46", red: "B3261E",
  amber: "A86200", muted: "5B6573", line: "D9DDE3", soft: "F2F5FA", ice: "CADCFC", white: "FFFFFF",
};
const THEME = {
  name: "DC Guardian",
  headFontFace: "Arial",
  bodyFontFace: "Calibri",
  colors: {
    dk1: HEX.navy, lt1: HEX.white, dk2: HEX.ink, lt2: HEX.soft,
    accent1: HEX.blue, accent2: HEX.cyan, accent3: HEX.green, accent4: HEX.red, accent5: HEX.amber, accent6: HEX.muted,
    hlink: HEX.blue, folHlink: "6B4FA0",
  },
};

async function icon(Comp, color, size = 256) {
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(Comp, { color: "#" + color, size: String(size) }));
  const png = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + png.toString("base64");
}

(async () => {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5
  pres.author = "Santiago Martín Montes Rubio";
  pres.title = "DC Guardian — Presentación del proyecto";
  pres.subject = "Sistema académico de control de acceso a un Data Center";
  pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
  const C = pres.SchemeColor;
  const W = 13.333, H = 7.5, M = 0.6;

  // ---------------------------------------------------------------- layouts
  pres.defineSlideMaster({
    title: "DARK",
    background: { color: HEX.navy },
    objects: [],
  });
  pres.defineSlideMaster({
    title: "CONTENT",
    background: { color: HEX.white },
    margin: [0.5, 0.6, 0.6, 0.6],
    objects: [
      { placeholder: { options: { name: "kicker", type: "body", x: M, y: 0.35, w: 9, h: 0.35, fontSize: 12, bold: true, color: C.accent2, charSpacing: 2, margin: 0, valign: "middle" }, text: "" } },
      { placeholder: { options: { name: "title", type: "title", x: M, y: 0.7, w: W - 2 * M, h: 0.85, fontSize: 30, bold: true, color: C.text1, margin: 0, valign: "top", align: "left", fontFace: THEME.headFontFace }, text: "" } },
      { text: { text: "DC Guardian · Control de acceso inteligente a un Data Center", options: { x: M, y: H - 0.45, w: 8, h: 0.3, fontSize: 10, color: HEX.muted, margin: 0 } } },
    ],
    slideNumber: { x: W - M - 0.6, y: H - 0.45, w: 0.6, h: 0.3, fontSize: 10, color: HEX.muted, align: "right" },
  });

  const shadow = () => ({ type: "outer", blur: 8, offset: 2, angle: 90, color: "8A94A6", opacity: 0.25 });
  let objN = 0;
  // name convention for animate.py: a<group>_<effect>_<n>
  const A = (g, eff = "fade") => `a${String(g).padStart(2, "0")}_${eff}_${objN++}`;

  function content(kicker, title, section) {
    const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: section });
    s.addText(kicker, { placeholder: "kicker" });
    s.addText(title, { placeholder: "title" });
    return s;
  }
  function card(s, x, y, w, h, opts = {}) {
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x, y, w, h, rectRadius: 0.12, fill: { color: opts.fill || HEX.white },
      line: { color: opts.line || HEX.line, width: 1 }, shadow: opts.noShadow ? undefined : shadow(), objectName: opts.name,
    });
  }
  async function iconCircle(s, Comp, x, y, d, bg, fg, name) {
    s.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: bg }, line: { color: bg }, objectName: name });
    s.addImage({ data: await icon(Comp, fg), x: x + d * 0.24, y: y + d * 0.24, w: d * 0.52, h: d * 0.52, objectName: name + "i" });
  }

  // ================================================================ 1. Portada
  pres.addSection({ title: "Introducción" });
  {
    const s = pres.addSlide({ masterName: "DARK", sectionTitle: "Introducción" });
    s.addText("PROYECTO ACADÉMICO · SEGURIDAD FÍSICA", { x: M, y: 1.25, w: 6.4, h: 0.35, fontSize: 12, bold: true, color: HEX.cyan, charSpacing: 2, margin: 0, isTextBox: true, objectName: A(1) });
    s.addText("DC Guardian", { x: M, y: 1.7, w: 6.4, h: 1.1, fontSize: 54, bold: true, color: HEX.white, fontFace: "Arial", margin: 0, isTextBox: true, objectName: A(1) });
    s.addText("Control de acceso multifactor a un Data Center con RFID, reconocimiento facial, autorizaciones temporales y un ESP32", { x: M, y: 2.9, w: 6.2, h: 1.1, fontSize: 19, color: HEX.ice, margin: 0, isTextBox: true, valign: "top", objectName: A(2) });
    const pills = ["ESP32", "FastAPI", "InsightFace", "SQLite", "HMAC-SHA256"];
    let px = M;
    pills.forEach((p) => {
      const w = 0.2 + p.length * 0.105;
      s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: px, y: 4.3, w, h: 0.38, rectRadius: 0.19, fill: { color: "16305A" }, line: { color: HEX.cyan, width: 1 }, objectName: A(3) });
      s.addText(p, { x: px, y: 4.3, w, h: 0.38, fontSize: 12, color: HEX.white, align: "center", valign: "middle", margin: 0, isTextBox: true, objectName: A(3) });
      px += w + 0.15;
    });
    s.addText([{ text: "Santiago Martín Montes Rubio", options: { bold: true, breakLine: true } }, { text: "Noviembre de 2026", options: { color: HEX.ice } }], { x: M, y: 5.5, w: 6, h: 0.75, fontSize: 14, color: HEX.white, margin: 0, isTextBox: true, objectName: A(4) });
    s.addImage({ path: CAP("02-panel.png"), x: 7.25, y: 1.25, w: 5.5, h: 3.4375, rounding: false, shadow: { type: "outer", blur: 18, offset: 4, angle: 90, color: "000000", opacity: 0.45 }, objectName: A(2, "zoom") });
    s.addText("Panel de control real (modo simulación, datos ficticios)", { x: 7.25, y: 4.8, w: 5.5, h: 0.3, fontSize: 11, color: HEX.ice, margin: 0, isTextBox: true, objectName: A(4) });
    s.addNotes(
      "Presento DC Guardian, un sistema académico de control de acceso a un centro de datos ficticio. " +
      "La idea central: para abrir la puerta no basta con una sola credencial. Se combinan una tarjeta RFID, el rostro del titular verificado con inteligencia artificial y una autorización temporal aprobada por un administrador. " +
      "La puerta es un servo controlado por un ESP32 que nunca decide por sí mismo: solo obedece respuestas firmadas por el backend. " +
      "La captura de la derecha es el panel real del sistema ejecutándose en modo simulación."
    );
  }

  // ================================================================ 2. Problemática
  {
    const s = content("01 · PROBLEMÁTICA", "Una sola credencial no protege una sala crítica", "Introducción");
    const items = [
      [fa.FaIdCard, "La tarjeta se copia", "El UID de una MIFARE Classic se lee y se clona con facilidad."],
      [fa.FaUserClock, "Registrado no es autorizado", "Estar dado de alta no debería abrir la puerta fuera de una ventana aprobada."],
      [fa.FaMicrochip, "El dispositivo no debe decidir", "Una cerradura que decide en local es fácil de manipular o suplantar."],
      [fa.FaHistory, "Sin trazas no hay control", "Intentos, decisiones y cambios deben quedar en un registro verificable."],
    ];
    const cw = 2.85, gap = 0.2, y = 2.2, ch = 3.4;
    for (let i = 0; i < items.length; i++) {
      const x = M + i * (cw + gap);
      const g = 1 + i;
      card(s, x, y, cw, ch, { name: A(g) });
      await iconCircle(s, items[i][0], x + 0.3, y + 0.35, 0.85, i === 0 ? "FBECEB" : "EAF1FB", i === 0 ? HEX.red : HEX.blue, A(g));
      s.addText(items[i][1], { x: x + 0.3, y: y + 1.4, w: cw - 0.6, h: 0.75, fontSize: 18, bold: true, color: HEX.navy, margin: 0, isTextBox: true, valign: "top", objectName: A(g) });
      s.addText(items[i][2], { x: x + 0.3, y: y + 2.25, w: cw - 0.6, h: 1.2, fontSize: 14, color: HEX.muted, margin: 0, isTextBox: true, valign: "top", objectName: A(g) });
    }
    s.addText("Riesgos tomados del análisis de diseño del proyecto (docs/FASE1_ARQUITECTURA.md §10) y de la sección de seguridad del README.", { x: M, y: 6.0, w: 12, h: 0.35, fontSize: 11, italic: true, color: HEX.muted, margin: 0, isTextBox: true, objectName: A(5) });
    s.addNotes(
      "En un centro de datos real el acceso físico se controla con varios factores y cada entrada queda registrada. " +
      "El proyecto parte de cuatro problemas: las tarjetas MIFARE Classic se clonan porque el UID es legible; estar registrado no significa estar autorizado en ese momento; si la cerradura decide localmente, basta con manipularla; y sin un registro íntegro no hay forma de auditar lo que pasó. " +
      "Estos riesgos están documentados en el análisis de diseño (riesgos R3, R6 y R7) y en la sección de seguridad del README. No se presentan estadísticas externas porque el repositorio no las contiene."
    );
  }

  // ================================================================ 3. Objetivo + regla fundamental
  {
    const s = content("02 · OBJETIVO", "Abrir solo cuando todo coincide, y dejar rastro de todo", "Introducción");
    s.addText("Objetivo general", { x: M, y: 2.0, w: 5.2, h: 0.4, fontSize: 16, bold: true, color: HEX.blue, margin: 0, isTextBox: true, objectName: A(1) });
    s.addText("Diseñar e implementar un sistema que conceda el acceso a una sala del Data Center solo cuando coinciden la tarjeta, el rostro del titular y una autorización temporal aprobada, con una puerta que falla en cerrado y una auditoría verificable.", { x: M, y: 2.45, w: 5.2, h: 2.2, fontSize: 17, color: HEX.ink, margin: 0, isTextBox: true, valign: "top", objectName: A(1) });
    // Regla fundamental visual
    const bx = 6.5;
    card(s, bx, 2.0, 2.9, 2.6, { fill: "F2F5FA", name: A(2) });
    s.addText([{ text: "Registro 1", options: { bold: true, fontSize: 18, color: HEX.navy, breakLine: true } }, { text: "Ingeniero + rostro", options: { fontSize: 14, color: HEX.muted, breakLine: true } }, { text: "Identifica. Nunca concede acceso.", options: { fontSize: 14, color: HEX.red, bold: true } }], { x: bx + 0.25, y: 2.15, w: 2.4, h: 2.3, margin: 0, isTextBox: true, valign: "middle", objectName: A(2) });
    card(s, bx + 3.35, 2.0, 2.9, 2.6, { fill: "E8F4EC", line: "A9D3B7", name: A(3) });
    s.addText([{ text: "Registro 2", options: { bold: true, fontSize: 18, color: HEX.navy, breakLine: true } }, { text: "Solicitud APROBADA con ventana horaria", options: { fontSize: 14, color: HEX.muted, breakLine: true } }, { text: "Lo único que consulta el motor.", options: { fontSize: 14, color: HEX.green, bold: true } }], { x: bx + 3.6, y: 2.15, w: 2.4, h: 2.3, margin: 0, isTextBox: true, valign: "middle", objectName: A(3) });
    s.addShape(pres.shapes.RIGHT_ARROW, { x: bx + 2.95, y: 3.1, w: 0.36, h: 0.4, fill: { color: HEX.cyan }, line: { color: HEX.cyan }, objectName: A(3) });
    // fail-closed badge
    card(s, bx, 4.95, 6.25, 1.0, { fill: HEX.navy, line: HEX.navy, name: A(4) });
    s.addImage({ data: await icon(fa.FaLock, HEX.cyan), x: bx + 0.3, y: 5.2, w: 0.5, h: 0.5, objectName: A(4) });
    s.addText([{ text: "Fail-closed: ", options: { bold: true, color: HEX.cyan } }, { text: "ante cualquier error, duda o pérdida de red, la puerta sigue cerrada.", options: { color: HEX.white } }], { x: bx + 1.0, y: 4.95, w: 5.1, h: 1.0, fontSize: 15, margin: 0, isTextBox: true, valign: "middle", objectName: A(4) });
    s.addText("Objetivos específicos en el reporte técnico (§5).", { x: M, y: 5.3, w: 5.2, h: 0.35, fontSize: 12, italic: true, color: HEX.muted, margin: 0, isTextBox: true, objectName: A(4) });
    s.addNotes(
      "El objetivo general es abrir la puerta solo cuando coinciden tres cosas: la tarjeta, el rostro del titular y una autorización temporal aprobada. " +
      "La regla fundamental del proyecto separa dos registros. El Registro 1 guarda al ingeniero y su biometría: sirve para identificar, pero nunca concede acceso. El Registro 2 son las solicitudes de autorización con su ventana horaria: es lo único que consulta el motor de acceso. " +
      "Y todo el sistema es fail-closed: si algo falla, la puerta permanece cerrada."
    );
  }

  // ================================================================ 4. Propuesta de solución
  pres.addSection({ title: "Solución" });
  {
    const s = content("03 · PROPUESTA", "Cuatro comprobaciones antes de mover el servo", "Solución");
    const steps = [
      [fa.FaIdCard, "Tarjeta RFID", "RC522 lee el UID. Solo identifica la tarjeta."],
      [fa.FaCalendarCheck, "Autorización vigente", "Solicitud APROBADA, dentro de su ventana y para esa área."],
      [md.MdFace, "Rostro 1:1", "InsightFace compara 5 fotogramas con el titular."],
      [fa.FaFileSignature, "Orden firmada", "GRANTED firmado con HMAC y ligado a la sesión."],
      [fa.FaDoorOpen, "Puerta abre 5 s", "Servo SG90 a 90° y cierre automático."],
    ];
    const n = steps.length, cw = 2.25, gap = (W - 2 * M - n * cw) / (n - 1), y = 2.25;
    s.addShape(pres.shapes.LINE, { x: M + cw / 2, y: y + 0.55, w: W - 2 * M - cw, h: 0, line: { color: HEX.line, width: 2 }, objectName: A(1, "wipe") });
    for (let i = 0; i < n; i++) {
      const x = M + i * (cw + gap);
      const last = i === n - 1;
      await iconCircle(s, steps[i][0], x + cw / 2 - 0.55, y, 1.1, last ? HEX.green : HEX.navy, last ? HEX.white : HEX.cyan, A(2 + i, "zoom"));
      s.addText(steps[i][1], { x, y: y + 1.3, w: cw, h: 0.45, fontSize: 17, bold: true, color: HEX.navy, align: "center", margin: 0, isTextBox: true, objectName: A(2 + i) });
      s.addText(steps[i][2], { x: x + 0.05, y: y + 1.8, w: cw - 0.1, h: 1.1, fontSize: 14, color: HEX.muted, align: "center", valign: "top", margin: 0, isTextBox: true, objectName: A(2 + i) });
    }
    card(s, M, 5.45, W - 2 * M, 0.85, { fill: "F2F5FA", noShadow: true, name: A(8) });
    s.addText([{ text: "Además: ", options: { bold: true, color: HEX.navy } }, { text: "alarma de intrusión interior (HC-SR04), botón de salida, alertas en tiempo real, auditoría encadenada y un simulador completo del ESP32.", options: { color: HEX.ink } }], { x: M + 0.3, y: 5.45, w: W - 2 * M - 0.6, h: 0.85, fontSize: 15, valign: "middle", margin: 0, isTextBox: true, objectName: A(8) });
    s.addNotes(
      "La solución encadena cuatro comprobaciones independientes. Primero, el lector RC522 lee el UID de la tarjeta, que solo identifica. " +
      "Segundo, el backend busca en el Registro 2 una solicitud aprobada, vigente y para esa área. Tercero, el kiosco con webcam envía cinco fotogramas e InsightFace los compara uno a uno con el titular de la tarjeta. " +
      "Cuarto, el backend vuelve a comprobar la autorización y responde GRANTED firmado con HMAC; el ESP32 solo abre si la firma es válida y corresponde a su propia sesión. " +
      "En el árbol de trabajo actual el HC-SR04 se movió dentro de la sala como alarma de intrusión y el pulsador pasó a ser botón de salida; estos cambios aún no están confirmados en git."
    );
  }

  // ================================================================ 5. Arquitectura (diagrama nativo animado)
  {
    const s = content("04 · ARQUITECTURA", "Un backend que decide, un ESP32 que obedece", "Solución");
    const actors = [
      [fa.FaUserTie, "Administrador", "Panel web · cookie JWT", "EAF1FB", HEX.blue],
      [fa.FaCamera, "Kiosco facial", "Navegador + webcam", "E6F6F8", HEX.cyan],
      [fa.FaMicrochip, "ESP32 + LCD", "RC522 · HC-SR04 · SG90", "FBF2E4", HEX.amber],
    ];
    const ax = M, aw = 3.0, ah = 1.05;
    for (let i = 0; i < actors.length; i++) {
      const y = 2.0 + i * 1.45;
      card(s, ax, y, aw, ah, { name: A(1) });
      await iconCircle(s, actors[i][0], ax + 0.18, y + 0.2, 0.65, actors[i][3], actors[i][4], A(1));
      s.addText([{ text: actors[i][1], options: { bold: true, fontSize: 15, color: HEX.navy, breakLine: true } }, { text: actors[i][2], options: { fontSize: 12, color: HEX.muted } }], { x: ax + 0.95, y, w: aw - 1.05, h: ah, margin: 0, valign: "middle", isTextBox: true, objectName: A(1) });
    }
    // backend block
    const bx = 4.75, bw = 5.15, by = 1.85, bh = 4.35;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: bx, y: by, w: bw, h: bh, rectRadius: 0.15, fill: { color: HEX.navy }, line: { color: HEX.navy }, shadow: shadow(), objectName: A(3) });
    s.addText([{ text: "Backend FastAPI", options: { bold: true, fontSize: 18, color: HEX.white, breakLine: true } }, { text: "72 rutas REST + WebSocket · routers → services → models", options: { fontSize: 12, color: HEX.ice } }], { x: bx + 0.3, y: by + 0.15, w: bw - 0.6, h: 0.75, margin: 0, isTextBox: true, objectName: A(3) });
    const chips = ["Motor de acceso", "Visión facial", "Auditoría HMAC", "Alertas", "WebSocket", "Scheduler", "Gateway /device", "Kiosco /vision"];
    chips.forEach((c, i) => {
      const cx = bx + 0.3 + (i % 2) * 2.35, cy = by + 1.1 + Math.floor(i / 2) * 0.78;
      s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: cx, y: cy, w: 2.2, h: 0.6, rectRadius: 0.1, fill: { color: "16305A" }, line: { color: i < 2 ? HEX.cyan : "2C4A78", width: 1 }, objectName: A(4) });
      s.addText(c, { x: cx, y: cy, w: 2.2, h: 0.6, fontSize: 13, color: HEX.white, align: "center", valign: "middle", margin: 0, isTextBox: true, objectName: A(4) });
    });
    // connectors actors -> backend
    const labels = ["REST + JWT", "5 JPEG · token kiosco", "HTTP firmado HMAC"];
    for (let i = 0; i < 3; i++) {
      const y = 2.0 + i * 1.45 + ah / 2;
      s.addShape(pres.shapes.LINE, { x: ax + aw, y, w: bx - ax - aw, h: 0, line: { color: HEX.muted, width: 1.5, endArrowType: "triangle", beginArrowType: i === 2 ? "triangle" : undefined }, objectName: A(2, "wipe") });
      s.addText(labels[i], { x: ax + aw + 0.05, y: y - 0.36, w: bx - ax - aw - 0.1, h: 0.3, fontSize: 11, color: HEX.muted, align: "center", margin: 0, isTextBox: true, objectName: A(2) });
    }
    // DB
    s.addShape(pres.shapes.LINE, { x: bx + bw, y: by + bh / 2, w: 0.6, h: 0, line: { color: HEX.muted, width: 1.5, endArrowType: "triangle", beginArrowType: "triangle" }, objectName: A(5, "wipe") });
    s.addShape(pres.shapes.CAN, { x: 10.55, y: 2.75, w: 2.15, h: 2.55, fill: { color: "EAF1FB" }, line: { color: HEX.blue, width: 1.5 }, objectName: A(5) });
    s.addText([{ text: "SQLite (WAL)", options: { bold: true, fontSize: 15, color: HEX.navy, breakLine: true } }, { text: "Registro 1 · Registro 2 · sesiones · alertas · auditoría", options: { fontSize: 12, color: HEX.muted } }], { x: 10.65, y: 3.35, w: 1.95, h: 1.7, align: "center", valign: "middle", margin: 0, isTextBox: true, objectName: A(5) });
    s.addText("Un único proceso sirve API, WebSocket y frontend (nativo o en Docker). La webcam la abre el navegador, no Python.", { x: M, y: 6.45, w: 12.1, h: 0.35, fontSize: 12, italic: true, color: HEX.muted, margin: 0, isTextBox: true, objectName: A(6) });
    s.addNotes(
      "La arquitectura es un monolito modular. A la izquierda los tres actores: el administrador usa el panel web con sesión JWT en cookie; el kiosco es un navegador con webcam que envía cinco fotogramas al backend; y el ESP32 habla por HTTP con peticiones y respuestas firmadas con HMAC-SHA256, nonce y marca de tiempo. " +
      "En el centro, el backend FastAPI con sus módulos: motor de acceso, visión facial con InsightFace, auditoría encadenada, alertas, WebSocket de eventos y un planificador que expira solicitudes y marca dispositivos fuera de línea. " +
      "Todo se persiste en SQLite en modo WAL. El mismo proceso sirve el frontend, por eso se puede desplegar con un solo contenedor Docker. El recuento de 72 rutas REST, 10 de ellas solo en modo simulación, se obtuvo contando los decoradores de los routers."
    );
  }

  // ================================================================ 6. Tecnologías
  {
    const s = content("05 · TECNOLOGÍAS", "Un stack ligero, reproducible y sin frameworks de frontend", "Solución");
    const cols = [
      [fa.FaPython, "Backend", ["Python 3.12", "FastAPI + Uvicorn", "SQLAlchemy 2 + Alembic", "Pydantic Settings"], HEX.blue],
      [fa.FaBrain, "Visión (IA)", ["InsightFace buffalo_l", "onnxruntime (CPU)", "OpenCV headless", "NumPy"], HEX.cyan],
      [fa.FaDesktop, "Frontend", ["HTML + CSS + JS", "Módulos ES, sin build", "WebSocket nativo", "getUserMedia"], HEX.blue],
      [fa.FaMicrochip, "Firmware", ["ESP32 · Arduino-ESP32", "FreeRTOS · C++17", "PlatformIO", "MFRC522 · ESP32Servo"], HEX.amber],
      [fa.FaShieldAlt, "Seguridad y despliegue", ["HMAC-SHA256 · Fernet", "PyJWT · bcrypt", "Docker Compose", "pytest · Unity"], HEX.green],
    ];
    const cw = 2.25, gap = (W - 2 * M - 5 * cw) / 4, y = 2.05, ch = 3.9;
    for (let i = 0; i < cols.length; i++) {
      const x = M + i * (cw + gap);
      card(s, x, y, cw, ch, { name: A(1 + i) });
      await iconCircle(s, cols[i][0], x + 0.25, y + 0.3, 0.75, "F2F5FA", cols[i][4], A(1 + i));
      s.addText(cols[i][1], { x: x + 0.25, y: y + 1.2, w: cw - 0.4, h: 0.45, fontSize: 16, bold: true, color: HEX.navy, margin: 0, isTextBox: true, objectName: A(1 + i) });
      s.addText(cols[i][2].map((t, k) => ({ text: t, options: { bullet: { indent: 12 }, breakLine: k < cols[i][2].length - 1 } })), { x: x + 0.2, y: y + 1.75, w: cw - 0.35, h: 2.0, fontSize: 13, color: HEX.ink, margin: 0, paraSpaceAfter: 6, valign: "top", isTextBox: true, objectName: A(1 + i) });
    }
    s.addText("Python 3.12 por compatibilidad de InsightFace y onnxruntime (no 3.13/3.14). Versiones fijadas en backend/uv.lock y requirements.lock.txt.", { x: M, y: 6.2, w: 12.1, h: 0.35, fontSize: 12, italic: true, color: HEX.muted, margin: 0, isTextBox: true, objectName: A(6) });
    s.addNotes(
      "Backend en Python 3.12 con FastAPI, SQLAlchemy 2 y Alembic para migraciones; la versión de Python está fijada porque InsightFace y onnxruntime no tienen soporte para 3.13 o 3.14. " +
      "La parte de inteligencia artificial usa InsightFace con el modelo buffalo_l, que genera embeddings faciales de 512 dimensiones, ejecutado en CPU con onnxruntime. " +
      "El frontend es HTML, CSS y JavaScript nativo con módulos ES, sin paso de compilación. El firmware está en C++17 sobre Arduino-ESP32 y FreeRTOS, compilado con PlatformIO. " +
      "Para la seguridad: HMAC-SHA256 en el protocolo del ESP32 y en la auditoría, Fernet para cifrar secretos y embeddings en reposo, bcrypt para contraseñas y JWT para la sesión. Se despliega con Docker Compose y se prueba con pytest y Unity."
    );
  }

  // ================================================================ 7. Fuentes de datos y adquisición
  pres.addSection({ title: "Datos" });
  {
    const s = content("06 · FUENTES DE DATOS", "Los datos nacen en cuatro puntos y terminan en SQLite", "Datos");
    const src = [
      [fa.FaIdCard, "Lector RC522", "UID de la tarjeta (4 o 7 bytes) en cada pasada"],
      [fa.FaCamera, "Webcam del kiosco", "5 fotogramas JPEG por verificación, solo en memoria"],
      [fa.FaWifi, "Telemetría del ESP32", "Latido cada 15 s: estado, puerta, distancia, RSSI, heap, sensores"],
      [fa.FaKeyboard, "Panel de administración", "Ingenieros, tarjetas, áreas y solicitudes"],
    ];
    for (let i = 0; i < src.length; i++) {
      const y = 1.95 + i * 1.08;
      card(s, M, y, 5.6, 0.9, { name: A(1 + i) });
      await iconCircle(s, src[i][0], M + 0.18, y + 0.14, 0.62, "EAF1FB", HEX.blue, A(1 + i));
      s.addText([{ text: src[i][1], options: { bold: true, fontSize: 15, color: HEX.navy, breakLine: true } }, { text: src[i][2], options: { fontSize: 12.5, color: HEX.muted } }], { x: M + 0.95, y, w: 4.55, h: 0.9, valign: "middle", margin: 0, isTextBox: true, objectName: A(1 + i) });
    }
    s.addShape(pres.shapes.RIGHT_ARROW, { x: 6.45, y: 3.55, w: 0.6, h: 0.55, fill: { color: HEX.cyan }, line: { color: HEX.cyan }, objectName: A(5) });
    // tables
    const tx = 7.3, tw = 5.43;
    card(s, tx, 1.95, tw, 4.15, { fill: "F2F5FA", noShadow: true, name: A(6) });
    s.addText("Base de datos SQLite · 5 migraciones Alembic", { x: tx + 0.25, y: 2.05, w: tw - 0.5, h: 0.45, fontSize: 15, bold: true, color: HEX.navy, margin: 0, isTextBox: true, objectName: A(6) });
    const rows = [
      ["engineers · face_embeddings", "Registro 1 (embeddings cifrados)"],
      ["authorization_requests", "Registro 2: ventanas aprobadas"],
      ["rfid_cards · areas · devices", "Catálogos y secretos cifrados"],
      ["access_sessions", "Cada intento: estado, motivo, similitud"],
      ["alerts · audit_log", "Alertas y cadena de hashes"],
      ["device_nonces · admins", "Anti-replay y cuentas"],
    ];
    s.addTable(rows.map((r) => [{ text: r[0], options: { fontFace: "Courier New", fontSize: 11.5, color: HEX.navy, bold: true } }, { text: r[1], options: { fontSize: 12.5, color: HEX.ink } }]),
      { x: tx + 0.25, y: 2.6, w: tw - 0.5, colW: [2.45, tw - 0.5 - 2.45], rowH: 0.52, border: { type: "solid", pt: 0.75, color: HEX.line }, fill: { color: HEX.white }, valign: "middle", margin: [0, 0.08, 0, 0.08], objectName: A(7) });
    s.addText("Sin CSV ni APIs externas: todos los datos los genera el propio sistema. Fotografías nunca guardadas.", { x: M, y: 6.35, w: 12.1, h: 0.35, fontSize: 12, italic: true, color: HEX.muted, margin: 0, isTextBox: true, objectName: A(8) });
    s.addNotes(
      "El proyecto no consume CSV, APIs externas ni conjuntos de datos públicos: todos los datos los produce el propio sistema. " +
      "Hay cuatro fuentes: el lector RC522 entrega el UID de la tarjeta; la webcam del kiosco captura cinco fotogramas que se procesan en memoria y nunca se escriben a disco; el ESP32 envía un latido cada 15 segundos con su estado, la distancia del sensor, la intensidad WiFi, la memoria libre y el estado de los sensores; y el panel de administración da de alta ingenieros, tarjetas, áreas y solicitudes. " +
      "Todo termina en SQLite, con un esquema versionado en cinco migraciones Alembic. Los embeddings faciales y los secretos de los dispositivos se guardan cifrados."
    );
  }

  // ================================================================ 8. Procesamiento y validación
  {
    const s = content("07 · PROCESAMIENTO Y VALIDACIÓN", "Cada dato se valida antes de influir en una decisión", "Datos");
    const lanes = [
      ["Mensajes del ESP32", HEX.amber, ["Firma HMAC", "Reloj ±30 s", "Nonce único", "≤ 4 KiB", "Listas blancas"]],
      ["Imágenes faciales", HEX.cyan, ["Decodificar", "Calidad", "Embedding", "Coseno 1:1", "Liveness"]],
      ["Registros del sistema", HEX.blue, ["UID normalizado", "Fechas UTC", "Máquina de estados", "Auditoría HMAC", "Evento WebSocket"]],
    ];
    for (let l = 0; l < lanes.length; l++) {
      const y = 2.0 + l * 1.38;
      s.addText(lanes[l][0], { x: M, y, w: 2.35, h: 1.0, fontSize: 15, bold: true, color: HEX.navy, valign: "middle", margin: 0, isTextBox: true, objectName: A(1 + l) });
      const cw = 1.85, gx = 0.07;
      for (let k = 0; k < 5; k++) {
        const x = M + 2.45 + k * (cw + gx);
        s.addShape(k === 0 ? pres.shapes.PENTAGON : pres.shapes.CHEVRON, { x, y: y + 0.1, w: cw, h: 0.8, fill: { color: k === 4 ? lanes[l][1] : "F2F5FA" }, line: { color: lanes[l][1], width: 1.25 }, objectName: A(1 + l, "wipe") });
        s.addText(lanes[l][2][k], { x: x + (k === 0 ? 0.1 : 0.36), y: y + 0.1, w: cw - 0.62, h: 0.8, fontSize: 12.5, bold: k === 4, color: k === 4 ? HEX.white : HEX.ink, align: "center", valign: "middle", margin: 0, isTextBox: true, objectName: A(1 + l, "wipe") });
      }
    }
    card(s, M, 6.1, W - 2 * M, 0.6, { fill: "FBECEB", line: "E8B4B0", noShadow: true, name: A(4) });
    s.addText([{ text: "Si cualquier paso falla: ", options: { bold: true, color: HEX.red } }, { text: "se rechaza con un motivo codificado, se registra en la auditoría y, si procede, se genera una alerta.", options: { color: HEX.ink } }], { x: M + 0.25, y: 6.1, w: W - 2 * M - 0.5, h: 0.6, fontSize: 14, valign: "middle", margin: 0, isTextBox: true, objectName: A(4) });
    s.addNotes(
      "No hay un proceso ETL clásico: el procesamiento consiste en validar y transformar cada dato antes de que influya en una decisión. " +
      "Los mensajes del ESP32 se aceptan solo si la firma HMAC es correcta, el reloj está dentro de ±30 segundos, el nonce no se ha usado antes y el cuerpo no supera 4 KiB; los campos se validan con listas blancas y rangos. " +
      "Las imágenes faciales se decodifican, pasan un control de calidad —un solo rostro, tamaño mínimo de 80 píxeles, nitidez por varianza del laplaciano y pose frontal—, se convierten en un embedding de 512 dimensiones, se comparan por similitud coseno con el titular y se aplica una prueba de vida básica. " +
      "En el registro, los UID se normalizan, las fechas se guardan siempre en UTC, los estados siguen máquinas de estados y cada acción entra en una auditoría encadenada con HMAC antes de publicarse por WebSocket."
    );
  }

  // ================================================================ 9. Funcionamiento interno: flujo de acceso
  pres.addSection({ title: "Funcionamiento" });
  {
    const s = content("08 · FUNCIONAMIENTO INTERNO", "De la tarjeta a la puerta en seis pasos", "Funcionamiento");
    const steps = [
      ["Pasa la tarjeta", "ESP32 envía el UID firmado. LCD: RFID DETECTADO"],
      ["Valida permisos", "Tarjeta activa, ingeniero activo, solicitud vigente"],
      ["Captura el rostro", "El kiosco recibe el aviso por WebSocket y toma 5 fotos"],
      ["Verifica 1:1", "Similitud ≥ 0,45 en al menos 3 de 5 y liveness"],
      ["Revalida y firma", "Comprueba de nuevo la autorización y firma GRANTED"],
      ["Abre y registra", "Servo 5 s, cierre automático y auditoría"],
    ];
    const n = 6, cw = 1.88, gap = (W - 2 * M - n * cw) / (n - 1), y = 2.25;
    s.addShape(pres.shapes.LINE, { x: M + 0.35, y: y + 0.35, w: W - 2 * M - 0.7, h: 0, line: { color: HEX.cyan, width: 2.5 }, objectName: A(1, "wipe") });
    for (let i = 0; i < n; i++) {
      const x = M + i * (cw + gap);
      s.addShape(pres.shapes.OVAL, { x, y, w: 0.7, h: 0.7, fill: { color: i === n - 1 ? HEX.green : HEX.navy }, line: { color: HEX.white, width: 2 }, objectName: A(2 + i, "zoom") });
      s.addText(String(i + 1), { x, y, w: 0.7, h: 0.7, fontSize: 18, bold: true, color: HEX.white, align: "center", valign: "middle", margin: 0, isTextBox: true, objectName: A(2 + i, "zoom") });
      s.addText(steps[i][0], { x, y: y + 0.95, w: cw, h: 0.45, fontSize: 15.5, bold: true, color: HEX.navy, margin: 0, isTextBox: true, objectName: A(2 + i) });
      s.addText(steps[i][1], { x, y: y + 1.45, w: cw, h: 1.3, fontSize: 13, color: HEX.muted, valign: "top", margin: 0, isTextBox: true, objectName: A(2 + i) });
    }
    // two outcome cards
    card(s, M, 5.15, 5.95, 1.2, { fill: "E8F4EC", line: "A9D3B7", noShadow: true, name: A(8) });
    s.addText([{ text: "Salida", options: { bold: true, color: HEX.green, breakLine: true } }, { text: "Segunda pasada con rostro, sin exigir autorización, o botón interior si hay alguien dentro: nadie queda atrapado.", options: { color: HEX.ink } }], { x: M + 0.25, y: 5.15, w: 5.5, h: 1.2, fontSize: 13.5, valign: "middle", margin: 0, isTextBox: true, objectName: A(8) });
    card(s, M + 6.18, 5.15, 5.95, 1.2, { fill: "FBECEB", line: "E8B4B0", noShadow: true, name: A(9) });
    s.addText([{ text: "Denegación", options: { bold: true, color: HEX.red, breakLine: true } }, { text: "25 motivos codificados (tarjeta, autorización, rostro, tiempo…). El LCD muestra el motivo y se crea una alerta.", options: { color: HEX.ink } }], { x: M + 6.43, y: 5.15, w: 5.5, h: 1.2, fontSize: 13.5, valign: "middle", margin: 0, isTextBox: true, objectName: A(9) });
    s.addNotes(
      "Así funciona una entrada. Uno: el ingeniero pasa la tarjeta y el ESP32 envía el UID en una petición firmada; el LCD muestra RFID DETECTADO. " +
      "Dos: el backend comprueba que la tarjeta está activa y vinculada, que el ingeniero está activo y que existe una solicitud aprobada y vigente para esa área. " +
      "Tres: el kiosco recibe el aviso por WebSocket y captura cinco fotogramas. Cuatro: InsightFace exige similitud de al menos 0,45 en al menos tres de los cinco, y que los fotogramas no sean idénticos. " +
      "Cinco: justo antes de conceder se vuelve a comprobar la autorización, por si se revocó mientras tanto, y se firma GRANTED. Seis: el servo abre cinco segundos y todo queda auditado. " +
      "La salida exige también el rostro pero no una autorización vigente, para que nadie quede encerrado. El motor define 25 códigos de motivo de denegación."
    );
  }

  // ================================================================ 10. Funcionalidades
  {
    const s = content("09 · FUNCIONALIDADES", "Todo el ciclo: alta, autorización, acceso y auditoría", "Funcionamiento");
    const f = [
      [fa.FaUsers, "Registro de ingenieros", "ID ENG-NNNN, estados y borrado de datos personales"],
      [md.MdFace, "Registro facial", "3–5 muestras con control de calidad y detección de duplicados"],
      [fa.FaIdCard, "Tarjetas RFID", "Alta, vinculación, bloqueo, pérdida y baja"],
      [fa.FaClipboardCheck, "Solicitudes", "Ventana horaria y aprobación sin autoaprobarse"],
      [fa.FaDoorOpen, "Acceso multifactor", "Entrada y salida con decisión firmada"],
      [fa.FaBell, "Alertas", "Tarjeta desconocida, fallos repetidos, intrusión, dispositivo caído"],
      [fa.FaChartLine, "Panel en tiempo real", "KPIs, hardware, ingenieros dentro y eventos"],
      [fa.FaLink, "Auditoría encadenada", "Cadena de hashes HMAC verificable desde la UI"],
      [fa.FaGamepad, "Simulador del ESP32", "Peticiones firmadas reales y rostros sintéticos"],
    ];
    const cw = 3.95, ch = 1.25, gx = (W - 2 * M - 3 * cw) / 2, gy = 0.2;
    for (let i = 0; i < f.length; i++) {
      const x = M + (i % 3) * (cw + gx), y = 1.95 + Math.floor(i / 3) * (ch + gy);
      const g = 1 + Math.floor(i / 3);
      card(s, x, y, cw, ch, { name: A(g) });
      await iconCircle(s, f[i][0], x + 0.2, y + 0.27, 0.7, "EAF1FB", HEX.blue, A(g));
      s.addText([{ text: f[i][1], options: { bold: true, fontSize: 15, color: HEX.navy, breakLine: true } }, { text: f[i][2], options: { fontSize: 12.5, color: HEX.muted } }], { x: x + 1.05, y: y + 0.08, w: cw - 1.2, h: ch - 0.16, valign: "middle", margin: 0, isTextBox: true, objectName: A(g) });
    }
    s.addNotes(
      "Estas son las nueve funcionalidades principales, todas implementadas en el código. El administrador registra ingenieros con un identificador ENG-NNNN y puede borrar sus datos personales. " +
      "El registro facial pide entre tres y cinco muestras, controla la calidad y rechaza un rostro que ya pertenece a otro ingeniero. Las tarjetas se registran, vinculan, bloquean, marcan como perdidas o se dan de baja. " +
      "Las solicitudes tienen ventana horaria y nadie puede aprobarse a sí mismo; suspender a un ingeniero revoca sus autorizaciones. " +
      "El acceso es multifactor con decisión firmada; las alertas cubren tarjetas desconocidas, tres fallos en cinco minutos, intrusión, sensores y dispositivos caídos. " +
      "El panel se actualiza en tiempo real por WebSocket, la auditoría es una cadena de hashes verificable y el simulador permite probarlo todo sin hardware."
    );
  }

  // ================================================================ 11. Interfaz
  {
    const s = content("10 · INTERFAZ Y EXPERIENCIA DE USUARIO", "Doce pantallas web, sin instalar nada en el cliente", "Funcionamiento");
    s.addImage({ path: CAP("02-panel.png"), x: M, y: 1.85, w: 7.0, h: 4.375, shadow: shadow(), objectName: A(1, "zoom") });
    s.addText("Panel de control: KPIs, hardware, ingenieros dentro y denegaciones por motivo", { x: M, y: 6.3, w: 7.0, h: 0.3, fontSize: 11.5, color: HEX.muted, margin: 0, isTextBox: true, objectName: A(1) });
    const rx = 7.9, rw = 4.83, rh = rw / 2.4;
    s.addImage({ path: process.env.GEN + "/07-simulador-crop.png", x: rx, y: 1.85, w: rw, h: rh, shadow: shadow(), objectName: A(2, "zoom") });
    s.addText("Simulador del ESP32", { x: rx, y: 1.85 + rh + 0.05, w: rw, h: 0.3, fontSize: 11.5, color: HEX.muted, margin: 0, isTextBox: true, objectName: A(2) });
    s.addImage({ path: process.env.GEN + "/10-auditoria-crop.png", x: rx, y: 4.25, w: rw, h: rh, shadow: shadow(), objectName: A(3, "zoom") });
    s.addText("Auditoría con verificación de la cadena: «Íntegra»", { x: rx, y: 4.25 + rh + 0.05, w: rw, h: 0.3, fontSize: 11.5, color: HEX.muted, margin: 0, isTextBox: true, objectName: A(3) });
    s.addNotes(
      "La interfaz es web, en español, sin instalación en el cliente. Tiene doce páginas: inicio de sesión, panel, ingenieros, alta y ficha de ingeniero, tarjetas, solicitudes, accesos, alertas, auditoría, simulador y kiosco. " +
      "A la izquierda, el panel de control con indicadores, estado del hardware, quién está dentro y las denegaciones por motivo. A la derecha, el simulador del ESP32, que envía peticiones firmadas reales al mismo gateway que usa la placa, y la auditoría, que verifica la cadena de hashes y en este caso la marca como íntegra. " +
      "Las capturas son reales: se tomaron el 15 de noviembre de 2026 con el sistema en modo simulación, una base de datos aislada y los datos ficticios de la semilla. El kiosco con la cámara no se muestra en funcionamiento porque el navegador usado para las capturas no tenía webcam."
    );
  }

  // ================================================================ 12. IA
  pres.addSection({ title: "Resultados" });
  {
    const s = content("11 · INTELIGENCIA ARTIFICIAL", "Verificación facial 1:1 con InsightFace", "Resultados");
    const st = [["Calidad de imagen", "1 rostro · ≥ 80 px · nitidez · pose"], ["Embedding", "buffalo_l · 512 dimensiones"], ["Comparación 1:1", "coseno ≥ 0,45 en ≥ 3 de 5"], ["Liveness básica", "rechaza fotogramas idénticos"]];
    for (let i = 0; i < st.length; i++) {
      const y = 1.95 + i * 1.0;
      s.addShape(pres.shapes.OVAL, { x: M, y: y + 0.12, w: 0.55, h: 0.55, fill: { color: HEX.cyan }, line: { color: HEX.cyan }, objectName: A(1 + i) });
      s.addText(String(i + 1), { x: M, y: y + 0.12, w: 0.55, h: 0.55, fontSize: 15, bold: true, color: HEX.white, align: "center", valign: "middle", margin: 0, isTextBox: true, objectName: A(1 + i) });
      s.addText([{ text: st[i][0], options: { bold: true, fontSize: 15, color: HEX.navy, breakLine: true } }, { text: st[i][1], options: { fontSize: 13, color: HEX.muted } }], { x: M + 0.75, y, w: 3.6, h: 0.8, valign: "middle", margin: 0, isTextBox: true, objectName: A(1 + i) });
    }
    s.addText("Embeddings cifrados en reposo; las fotografías no se guardan.", { x: M, y: 6.0, w: 4.3, h: 0.6, fontSize: 12, italic: true, color: HEX.muted, margin: 0, isTextBox: true, valign: "top", objectName: A(5) });
    // native combo chart: real similarity scores + threshold
    const labels = ["1", "2", "3", "4", "5", "6", "7", "8", "9"];
    const scores = [0.7835, 0.2936, 0.8371, 0.7222, 0.7251, 0.612, 0.6525, 0.6552, 0.6935];
    s.addText("Similitud real registrada con el ESP32 físico (15-11-2026)", { x: 5.25, y: 1.9, w: 7.5, h: 0.4, fontSize: 15, bold: true, color: HEX.navy, margin: 0, isTextBox: true, objectName: A(6) });
    s.addChart([
      { type: pres.charts.BAR, data: [{ name: "Aceptada", labels, values: scores.map((v) => (v >= 0.45 ? v : 0)) }, { name: "Rechazada", labels, values: scores.map((v) => (v < 0.45 ? v : 0)) }], options: { barGrouping: "stacked", chartColors: [HEX.green, HEX.red] } },
      { type: pres.charts.LINE, data: [{ name: "Umbral 0,45", labels, values: labels.map(() => 0.45) }], options: { chartColors: [HEX.amber], lineSize: 2, lineDash: "dash", lineDataSymbol: "none" } },
    ], {
      x: 5.25, y: 2.35, w: 7.5, h: 3.65, barGapWidthPct: 60,
      valAxisMinVal: 0, valAxisMaxVal: 1, valAxisMajorUnit: 0.2, valAxisLabelFormatCode: "0.0",
      catAxisLabelColor: HEX.muted, valAxisLabelColor: HEX.muted, catAxisLabelFontSize: 11, valAxisLabelFontSize: 11,
      catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt", legendFontFace: "+mn-lt",
      valGridLine: { color: "E3E7ED", size: 0.75 }, catGridLine: { style: "none" },
      showLegend: true, legendPos: "b", legendFontSize: 11, legendColor: HEX.muted,
      showCatAxisTitle: true, catAxisTitle: "Verificación (orden cronológico)", catAxisTitleFontSize: 11, catAxisTitleColor: HEX.muted,
      objectName: A(7, "wipe"),
    });
    s.addText("8 aceptadas (0,61–0,84) y 1 rechazada (0,29). Muestra pequeña de un único usuario: el umbral no está calibrado con una población real.", { x: 5.25, y: 6.05, w: 7.5, h: 0.55, fontSize: 12, italic: true, color: HEX.muted, margin: 0, isTextBox: true, valign: "top", objectName: A(8) });
    s.addNotes(
      "El componente de inteligencia artificial es la verificación facial uno a uno. No identifica entre todos los ingenieros: compara con el titular de la tarjeta, lo que reduce el riesgo de falsos positivos. " +
      "Cada fotograma pasa un control de calidad; InsightFace con el modelo buffalo_l obtiene un embedding de 512 dimensiones; se calcula la similitud coseno con las muestras registradas y se exige al menos 0,45 en tres de cinco fotogramas. La prueba de vida es básica: rechaza capturas idénticas o casi idénticas. " +
      "El gráfico muestra datos reales de la base de datos local del 15 de noviembre de 2026, con el firmware 1.0.0 del ESP32 y el modelo buffalo_l: ocho verificaciones aceptadas entre 0,61 y 0,84 y una rechazada con 0,29. Además hubo cinco reintentos por rostro no detectado, que no aparecen aquí. " +
      "Es una muestra de un solo usuario, así que no sirve para estimar tasas de falsa aceptación o falso rechazo. El README declara el umbral como no calibrado y la prueba de vida no detecta máscaras ni vídeos."
    );
  }

  // ================================================================ 13. Indicadores y resultados
  {
    const s = content("12 · INDICADORES Y RESULTADOS", "321 pruebas en verde y once aperturas reales con el ESP32", "Resultados");
    const kpis = [["321", "pruebas automatizadas aprobadas, 0 fallidas", HEX.green], ["11", "aperturas reales con ESP32 físico (6 entradas, 5 salidas)", HEX.blue], ["0,7–1,2 s", "de la decisión a la puerta abierta", HEX.cyan], ["38", "alertas generadas (4 de intrusión, CRITICAL)", HEX.red]];
    const kw = 2.85, kg = (W - 2 * M - 4 * kw) / 3;
    for (let i = 0; i < kpis.length; i++) {
      const x = M + i * (kw + kg);
      card(s, x, 1.9, kw, 1.55, { name: A(1 + i, "zoom") });
      s.addText(kpis[i][0], { x: x + 0.25, y: 1.98, w: kw - 0.5, h: 0.75, fontSize: 36, bold: true, color: kpis[i][2], margin: 0, isTextBox: true, fontFace: "Arial", objectName: A(1 + i, "zoom") });
      s.addText(kpis[i][1], { x: x + 0.25, y: 2.72, w: kw - 0.5, h: 0.65, fontSize: 12.5, color: HEX.muted, margin: 0, valign: "top", isTextBox: true, objectName: A(1 + i, "zoom") });
    }
    // native chart: tests per suite
    s.addText("Pruebas por suite (ejecutadas el 15-11-2026)", { x: M, y: 3.75, w: 6.6, h: 0.35, fontSize: 14, bold: true, color: HEX.navy, margin: 0, isTextBox: true, objectName: A(5) });
    s.addChart(pres.charts.BAR, [{ name: "Pruebas", labels: ["Backend: módulos", "Backend: E2E", "Backend: seguridad", "Firmware: nativas", "Firmware: integración"], values: [179, 31, 12, 86, 13] }], {
      x: M, y: 4.1, w: 6.6, h: 2.65, barDir: "bar", chartColors: [HEX.blue, HEX.blue, HEX.blue, HEX.cyan, HEX.cyan], invertedColors: [HEX.blue],
      showValue: true, dataLabelPosition: "outEnd", dataLabelColor: HEX.navy, dataLabelFontSize: 11, dataLabelFontFace: "+mn-lt",
      catAxisLabelColor: HEX.muted, valAxisLabelColor: HEX.muted, catAxisLabelFontSize: 11, valAxisLabelFontSize: 10,
      catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt", catAxisOrientation: "maxMin",
      valGridLine: { color: "E3E7ED", size: 0.75 }, catGridLine: { style: "none" }, showLegend: false, valAxisHidden: true,
      objectName: A(6, "wipe"),
    });
    // sessions chart
    s.addText("39 sesiones reales por resultado", { x: 7.45, y: 3.75, w: 5.3, h: 0.35, fontSize: 14, bold: true, color: HEX.navy, margin: 0, isTextBox: true, objectName: A(7) });
    s.addChart(pres.charts.BAR, [{ name: "Sesiones", labels: ["Tarjeta no registrada", "Concedido y cerrado", "Botón sin nadie dentro", "Otras denegaciones"], values: [12, 11, 8, 8] }], {
      x: 7.45, y: 4.1, w: 5.3, h: 2.65, barDir: "bar", chartColors: [HEX.red, HEX.green, HEX.red, HEX.red],
      showValue: true, dataLabelPosition: "outEnd", dataLabelColor: HEX.navy, dataLabelFontSize: 11, dataLabelFontFace: "+mn-lt",
      catAxisLabelColor: HEX.muted, valAxisLabelColor: HEX.muted, catAxisLabelFontSize: 11, valAxisLabelFontSize: 10,
      catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt", catAxisOrientation: "maxMin",
      valGridLine: { color: "E3E7ED", size: 0.75 }, catGridLine: { style: "none" }, showLegend: false, valAxisHidden: true,
      objectName: A(8, "wipe"),
    });
    s.addNotes(
      "Indicadores verificables. Ejecuté todas las suites el 15 de noviembre de 2026 sobre el árbol de trabajo actual: 222 pruebas del backend, 86 pruebas nativas del firmware con Unity y 13 de integración del firmware contra el gateway real; 321 en total, sin fallos. " +
      "Los demás datos vienen de la base de datos local del proyecto, que registra una sesión de pruebas con el ESP32 físico ese mismo día: 39 sesiones de acceso, de las cuales 11 terminaron en apertura y cierre correctos. Las 28 denegaciones incluyen 12 tarjetas no registradas y 8 pulsaciones del botón de salida sin nadie dentro, que el sistema debe rechazar. " +
      "Entre la decisión y la puerta abierta pasaron entre 0,7 y 1,2 segundos. Desde la tarjeta hasta la decisión, con rostro, entre 6 y 13 segundos, porque incluye el tiempo de la persona frente a la cámara y los reintentos; por eso no se puede afirmar que se cumpla el objetivo de diseño de 5 segundos. " +
      "Se generaron 38 alertas, cuatro de ellas de intrusión. Esta prueba con hardware no está documentada formalmente en docs; se infiere de la telemetría registrada (firmware 1.0.0, RSSI −64 dBm)."
    );
  }

  // ================================================================ 14. Conclusiones, limitaciones y mejoras
  pres.addSection({ title: "Cierre" });
  {
    const s = content("13 · CONCLUSIONES", "Un prototipo sólido con límites declarados", "Cierre");
    const cols = [
      [fa.FaCheckCircle, "Logros", HEX.green, "E8F4EC", ["Acceso multifactor fail-closed de extremo a extremo", "Protocolo firmado contra falsificación y replay", "Auditoría encadenada verificable", "Simulación completa y 321 pruebas"]],
      [fa.FaExclamationTriangle, "Limitaciones", HEX.amber, "FBF2E4", ["Umbral facial sin calibrar; liveness básica", "HTTP sin TLS en la LAN por defecto", "Secreto del ESP32 sin cifrar en flash", "Una instancia y SQLite"]],
      [fa.FaRocket, "Próximos pasos", HEX.blue, "EAF1FB", ["Calibrar el umbral con una población real", "Liveness activa o cámara de profundidad", "HTTPS con proxy y CA fijada", "Documentar y confirmar en git la prueba con hardware"]],
    ];
    const cw = 3.9, gx = (W - 2 * M - 3 * cw) / 2;
    for (let i = 0; i < 3; i++) {
      const x = M + i * (cw + gx), y = 1.95;
      card(s, x, y, cw, 4.0, { name: A(1 + i) });
      await iconCircle(s, cols[i][0], x + 0.3, y + 0.3, 0.75, cols[i][3], cols[i][2], A(1 + i));
      s.addText(cols[i][1], { x: x + 1.2, y: y + 0.3, w: cw - 1.4, h: 0.75, fontSize: 19, bold: true, color: HEX.navy, valign: "middle", margin: 0, isTextBox: true, objectName: A(1 + i) });
      s.addText(cols[i][4].map((t, k) => ({ text: t, options: { bullet: { indent: 14 }, breakLine: k < 3 } })), { x: x + 0.3, y: y + 1.3, w: cw - 0.55, h: 2.55, fontSize: 15, color: HEX.ink, paraSpaceAfter: 10, valign: "top", margin: 0, isTextBox: true, objectName: A(1 + i) });
    }
    s.addText("El propio README lo declara: proyecto académico, no apto para un control de acceso real.", { x: M, y: 6.25, w: 12.1, h: 0.3, fontSize: 12, italic: true, color: HEX.muted, margin: 0, isTextBox: true, objectName: A(4) });
    s.addNotes(
      "En conclusión, DC Guardian demuestra un control de acceso multifactor completo y fail-closed: la tarjeta sola, el rostro solo o el registro solo nunca abren la puerta. El protocolo firmado impide falsificar o reinyectar órdenes y la auditoría encadenada permite detectar manipulaciones. " +
      "Sus limitaciones están declaradas en el propio repositorio: el umbral facial no está calibrado y la prueba de vida es básica; por defecto el tráfico va por HTTP sin TLS, así que se puede leer aunque no falsificar; el secreto del ESP32 está en su flash sin cifrar; y es una sola instancia con SQLite. " +
      "Como trabajo futuro propongo calibrar el umbral con más personas, añadir una prueba de vida activa, poner HTTPS delante y, de forma inmediata, confirmar en git los cambios del sensor de intrusión y documentar la prueba con hardware real."
    );
  }

  // ================================================================ 15. Cierre
  {
    const s = pres.addSlide({ masterName: "DARK", sectionTitle: "Cierre" });
    s.addImage({ data: await icon(fa.FaShieldAlt, HEX.cyan), x: W / 2 - 0.5, y: 1.25, w: 1.0, h: 1.0, objectName: A(1, "zoom") });
    s.addText("Gracias", { x: 1, y: 2.45, w: W - 2, h: 1.0, fontSize: 48, bold: true, color: HEX.white, align: "center", margin: 0, isTextBox: true, fontFace: "Arial", objectName: A(1) });
    s.addText("¿Preguntas?", { x: 1, y: 3.45, w: W - 2, h: 0.6, fontSize: 22, color: HEX.ice, align: "center", margin: 0, isTextBox: true, objectName: A(2) });
    s.addText([
      { text: "Repositorio: ", options: { color: HEX.ice } },
      { text: "github.com/santymontes234-a11y/dc-guardian", options: { color: HEX.cyan, hyperlink: { url: "https://github.com/santymontes234-a11y/dc-guardian", tooltip: "Repositorio en GitHub" } } },
    ], { x: 1, y: 4.55, w: W - 2, h: 0.45, fontSize: 16, align: "center", margin: 0, isTextBox: true, objectName: A(3) });
    s.addText("Licencia MIT · Proyecto académico · Datos de demostración ficticios · Sin despliegue público", { x: 1, y: 5.1, w: W - 2, h: 0.4, fontSize: 13, color: HEX.ice, align: "center", margin: 0, isTextBox: true, objectName: A(3) });
    s.addText("Santiago Martín Montes Rubio · Noviembre de 2026", { x: 1, y: 6.3, w: W - 2, h: 0.4, fontSize: 13, color: HEX.white, align: "center", margin: 0, isTextBox: true, objectName: A(4) });
    s.addNotes(
      "Gracias por su atención. El código está en GitHub bajo licencia MIT; el enlace es funcional. El proyecto no tiene un despliegue público: se ejecuta en local con run.sh o con Docker Compose. " +
      "Nota: en la fecha de esta presentación la rama remota está en el commit 68afbe1; los dos últimos commits locales y los cambios del sensor de intrusión y del botón de salida aún no se han subido. Quedo atento a sus preguntas."
    );
  }

  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("written", OUT);
})().catch((e) => { console.error(e); process.exit(1); });
