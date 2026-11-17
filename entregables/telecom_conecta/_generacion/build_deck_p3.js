// Presentación del Proyecto Parcial 3 (Telecom Conecta) con pptxgenjs. Las animaciones se inyectan después
// con entregables/_generacion/animate.py (nombres aNN_<efecto>_<k>).
const path = require("path");
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa");
const { applyTheme } = require(process.env.SKILL_DIR + "/scripts/apply_theme.js");

const BASE = path.resolve(__dirname, "..");
const OUT = process.argv[2];
const F = (...p) => path.join(BASE, ...p);

const HEX = {
  navy: "0A1A33", ink: "1C2430", teal: "0E8A9A", cyan: "36C2D4", green: "1D7A46", red: "B3261E",
  amber: "B86E00", muted: "5B6573", line: "D9DDE3", soft: "EEF4F7", ice: "C9E7EE", white: "FFFFFF", magenta: "C2187A",
};
const THEME = {
  name: "Telecom Conecta",
  headFontFace: "Arial",
  bodyFontFace: "Calibri",
  colors: {
    dk1: HEX.navy, lt1: HEX.white, dk2: HEX.ink, lt2: HEX.soft,
    accent1: HEX.teal, accent2: HEX.cyan, accent3: HEX.green, accent4: HEX.red, accent5: HEX.amber, accent6: HEX.magenta,
    hlink: HEX.teal, folHlink: "6B4FA0",
  },
};

async function icon(Comp, color, size = 256) {
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(Comp, { color: "#" + color, size: String(size) }));
  return "image/png;base64," + (await sharp(Buffer.from(svg)).png().toBuffer()).toString("base64");
}
async function dims(file) { const m = await sharp(file).metadata(); return m.width / m.height; }

(async () => {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_WIDE";
  pres.author = "Equipo Telecom Conecta";
  pres.title = "Telecom Conecta — Maqueta segura (Proyecto Parcial 3)";
  pres.subject = "Control de acceso por zonas y sensores";
  pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
  const C = pres.SchemeColor;
  const W = 13.333, H = 7.5, M = 0.6;

  pres.defineSlideMaster({ title: "DARK", background: { color: HEX.navy }, objects: [] });
  pres.defineSlideMaster({
    title: "CONTENT",
    background: { color: HEX.white },
    margin: [0.5, 0.6, 0.6, 0.6],
    objects: [
      { placeholder: { options: { name: "kicker", type: "body", x: M, y: 0.35, w: 9, h: 0.35, fontSize: 12, bold: true, color: C.accent1, charSpacing: 2, margin: 0, valign: "middle" }, text: "" } },
      { placeholder: { options: { name: "title", type: "title", x: M, y: 0.7, w: W - 2 * M, h: 0.8, fontSize: 30, bold: true, color: C.text1, margin: 0, valign: "top", align: "left", fontFace: THEME.headFontFace }, text: "" } },
      { text: { text: "Telecom Conecta · Proyecto Parcial 3 · Centros de Datos · 17/11/2026", options: { x: M, y: H - 0.45, w: 9, h: 0.3, fontSize: 10, color: HEX.muted, margin: 0 } } },
    ],
    slideNumber: { x: W - M - 0.6, y: H - 0.45, w: 0.6, h: 0.3, fontSize: 10, color: HEX.muted, align: "right" },
  });

  const shadow = () => ({ type: "outer", blur: 8, offset: 2, angle: 90, color: "8A94A6", opacity: 0.25 });
  let objN = 0;
  const A = (g, eff = "fade") => `a${String(g).padStart(2, "0")}_${eff}_${objN++}`;
  const content = (kicker, title, section) => {
    const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: section });
    s.addText(kicker, { placeholder: "kicker" });
    s.addText(title, { placeholder: "title" });
    return s;
  };
  const card = (s, x, y, w, h, opts = {}) => s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x, y, w, h, rectRadius: 0.12, fill: { color: opts.fill || HEX.white }, line: { color: opts.line || HEX.line, width: 1 },
    shadow: opts.noShadow ? undefined : shadow(), objectName: opts.name,
  });
  async function iconCircle(s, Comp, x, y, d, bg, fg, name) {
    s.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: bg }, line: { color: bg }, objectName: name });
    s.addImage({ data: await icon(Comp, fg), x: x + d * 0.24, y: y + d * 0.24, w: d * 0.52, h: d * 0.52, objectName: name + "i" });
  }
  // Fit an image inside a box keeping its ratio (centered).
  async function fit(s, file, x, y, w, h, name, extra = {}) {
    const r = await dims(file);
    let iw = w, ih = w / r;
    if (ih > h) { ih = h; iw = h * r; }
    s.addImage({ path: file, x: x + (w - iw) / 2, y: y + (h - ih) / 2, w: iw, h: ih, objectName: name, ...extra });
    return { x: x + (w - iw) / 2, y: y + (h - ih) / 2, w: iw, h: ih };
  }

  // ============================================================ 1. Portada
  pres.addSection({ title: "Introducción" });
  {
    const s = pres.addSlide({ masterName: "DARK", sectionTitle: "Introducción" });
    s.addText("PROYECTO PARCIAL 3 · CENTROS DE DATOS · UNIDAD III", { x: M, y: 1.2, w: 6.2, h: 0.35, fontSize: 12, bold: true, color: HEX.cyan, charSpacing: 2, margin: 0, isTextBox: true, objectName: A(1) });
    s.addText("Telecom Conecta", { x: M, y: 1.65, w: 6.2, h: 1.0, fontSize: 50, bold: true, color: HEX.white, fontFace: "Arial", margin: 0, isTextBox: true, objectName: A(1) });
    s.addText("Maqueta segura: control de acceso por zonas y sensores para proteger el Servidor de clientes", { x: M, y: 2.75, w: 6.0, h: 1.1, fontSize: 19, color: HEX.ice, margin: 0, valign: "top", isTextBox: true, objectName: A(2) });
    const pills = ["Código QR", "RFID + rostro", "DHT11", "HC-SR04", "ESP32"];
    let px = M;
    pills.forEach((p) => {
      const w = 0.3 + p.length * 0.1;
      s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: px, y: 4.15, w, h: 0.38, rectRadius: 0.19, fill: { color: "13304F" }, line: { color: HEX.cyan, width: 1 }, objectName: A(3) });
      s.addText(p, { x: px, y: 4.15, w, h: 0.38, fontSize: 12, color: HEX.white, align: "center", valign: "middle", margin: 0, isTextBox: true, objectName: A(3) });
      px += w + 0.12;
    });
    s.addText([{ text: "Equipo: [nombre del equipo]", options: { bold: true, breakLine: true } }, { text: "[Integrante 1] · [Integrante 2] · [Integrante 3] · [Integrante 4]", options: { color: HEX.ice, breakLine: true } }, { text: "17 de noviembre de 2026", options: { color: HEX.ice } }],
      { x: M, y: 5.25, w: 6.2, h: 1.1, fontSize: 14, color: HEX.white, margin: 0, isTextBox: true, objectName: A(4) });
    await fit(s, F("diagramas/plano_telecom_conecta.png"), 7.0, 1.2, 5.75, 4.4, A(2, "zoom"), { shadow: { type: "outer", blur: 18, offset: 4, angle: 90, color: "000000", opacity: 0.45 } });
    s.addText("Plano de seguridad actualizado (redibujo del Parcial 1)", { x: 7.0, y: 5.75, w: 5.75, h: 0.3, fontSize: 11, color: HEX.ice, margin: 0, align: "center", isTextBox: true, objectName: A(4) });
    s.addNotes("Somos el equipo de Telecom Conecta, escenario 8. Nuestra zona crítica es el Servidor de clientes: datos de abonados, contratos y facturación. Partimos de la maqueta del Parcial 1 y le agregamos control de acceso por zonas, sensores ambientales y de intrusión, protocolos de respuesta y bitácora. Todo funciona con hardware real: un ESP32 conectado al sistema DC Guardian.");
  }

  // ============================================================ 2. Escenario
  {
    const s = content("ESCENARIO", "Cuatro roles, una zona crítica y dos puertas reales", "Introducción");
    const roles = [
      [fa.FaUserShield, "Administrador de TI", "Entra a todas las zonas con autorización vigente", HEX.teal],
      [fa.FaNetworkWired, "Ingeniero de red", "Sala de servidores solo en su ventana de mantenimiento", HEX.teal],
      [fa.FaBroom, "Personal de limpieza", "Solo recepción; a la sala, únicamente escoltado", HEX.amber],
      [fa.FaTruck, "Proveedor", "Pase QR temporal; siempre escoltado", HEX.amber],
    ];
    for (let i = 0; i < 4; i++) {
      const x = M + (i % 2) * 3.75, y = 1.75 + Math.floor(i / 2) * 2.05;
      card(s, x, y, 3.55, 1.85, { name: A(1 + Math.floor(i / 2)) });
      await iconCircle(s, roles[i][0], x + 0.25, y + 0.3, 0.7, roles[i][3], HEX.white, A(1 + Math.floor(i / 2)));
      s.addText(roles[i][1], { x: x + 1.1, y: y + 0.25, w: 2.3, h: 0.5, fontSize: 16, bold: true, color: HEX.navy, margin: 0, valign: "middle", isTextBox: true, objectName: A(1 + Math.floor(i / 2)) });
      s.addText(roles[i][2], { x: x + 1.1, y: y + 0.8, w: 2.3, h: 0.9, fontSize: 13, color: HEX.ink, margin: 0, valign: "top", isTextBox: true, objectName: A(1 + Math.floor(i / 2)) });
    }
    const zx = 8.35, zw = W - M - zx;
    card(s, zx, 1.75, zw, 3.9, { fill: HEX.navy, line: HEX.navy, name: A(3) });
    s.addText("Zonas", { x: zx + 0.3, y: 1.95, w: zw - 0.6, h: 0.45, fontSize: 18, bold: true, color: HEX.cyan, margin: 0, isTextBox: true, objectName: A(3) });
    s.addText([
      { text: "Z1 Entrada principal", options: { bold: true, color: HEX.white, breakLine: true } },
      { text: "Código QR → LED verde", options: { color: HEX.ice, breakLine: true } },
      { text: " ", options: { fontSize: 6, breakLine: true } },
      { text: "Z2 Sala de servidores", options: { bold: true, color: HEX.white, breakLine: true } },
      { text: "RFID + rostro → servo", options: { color: HEX.ice, breakLine: true } },
      { text: " ", options: { fontSize: 6, breakLine: true } },
      { text: "Z3 Eléctrica · Z4 Control", options: { bold: true, color: HEX.white, breakLine: true } },
      { text: "Restringidas (representadas)", options: { color: HEX.ice } },
    ], { x: zx + 0.3, y: 2.5, w: zw - 0.6, h: 3.0, fontSize: 15, margin: 0, valign: "top", isTextBox: true, objectName: A(3) });
    s.addText("Menor privilegio: cada rol entra solo donde su trabajo lo exige y en su horario.", { x: M, y: 6.0, w: 12.1, h: 0.4, fontSize: 14, italic: true, color: HEX.teal, margin: 0, isTextBox: true, objectName: A(4) });
    s.addNotes("La práctica nos asignó cuatro roles: administrador de TI, ingeniero de red, personal de limpieza y proveedor. Definimos dos zonas funcionales: la entrada principal, con código QR, y la sala de servidores, donde está el Servidor de clientes, con tarjeta RFID más reconocimiento facial. La sala eléctrica y la de control están representadas en la maqueta. El criterio es el menor privilegio.");
  }

  // ============================================================ 3. Plano
  pres.addSection({ title: "Diseño" });
  {
    const s = content("D1 · DIAGRAMA ACTUALIZADO", "Plano de seguridad: zonas, dispositivos y salidas", "Diseño");
    await fit(s, F("diagramas/plano_telecom_conecta.png"), M, 1.55, 12.1, 5.3, A(1, "zoom"));
    s.addNotes("Este es el plano del Parcial 1 actualizado. Los contornos de color marcan las zonas: Z1 recepción, Z2 sala de servidores en magenta con los racks del Servidor de clientes resaltados, Z3 eléctrica y Z4 control. En azul están los dispositivos de acceso, en ámbar los sensores y en rojo las alarmas. Las flechas verdes son las rutas de evacuación: las salidas de emergencia tienen barra antipánico y nunca dependen del control de acceso.");
  }

  // ============================================================ 4. Métodos
  {
    const s = content("DECISIONES", "Por qué QR en la entrada y RFID + rostro en la sala", "Diseño");
    const cols = [
      [fa.FaQrcode, "Entrada principal · QR", ["Barato y rápido de reemplazar: se imprime o va en el celular", "Ideal para proveedores y limpieza, que rotan", "Si se pierde, se revoca al instante", "Además exige una autorización vigente (Registro 2)"], HEX.teal],
      [fa.FaUserLock, "Sala de servidores · 2 factores", ["Algo que tienes: tarjeta RFID RC522", "Algo que eres: rostro (≥ 3 de 5 cuadros, umbral 0.45)", "Una tarjeta clonada o prestada no basta", "El ESP32 solo abre con una respuesta firmada (HMAC)"], HEX.magenta],
    ];
    for (let i = 0; i < 2; i++) {
      const x = M + i * 3.85, y = 1.7, w = 3.65;
      card(s, x, y, w, 4.55, { name: A(1 + i) });
      await iconCircle(s, cols[i][0], x + 0.25, y + 0.25, 0.7, cols[i][3], HEX.white, A(1 + i));
      s.addText(cols[i][1], { x: x + 1.05, y: y + 0.25, w: w - 1.2, h: 0.7, fontSize: 16, bold: true, color: HEX.navy, margin: 0, valign: "middle", isTextBox: true, objectName: A(1 + i) });
      s.addText(cols[i][2].map((t, k) => ({ text: t, options: { bullet: { indent: 14 }, breakLine: k < 3 } })), { x: x + 0.25, y: y + 1.2, w: w - 0.45, h: 3.2, fontSize: 14, color: HEX.ink, paraSpaceAfter: 8, valign: "top", margin: 0, isTextBox: true, objectName: A(1 + i) });
    }
    await fit(s, F("capturas/entrada_qr.png"), 8.4, 1.7, 4.33, 4.0, A(3, "zoom"), { shadow: shadow() });
    s.addText("Lector QR real: acceso permitido y LED verde", { x: 8.4, y: 5.85, w: 4.33, h: 0.3, fontSize: 11, color: HEX.muted, align: "center", margin: 0, isTextBox: true, objectName: A(3) });
    s.addNotes("Elegimos tres métodos del catálogo. En la entrada, código QR: es barato, sirve para visitas y se revoca al instante; pero el QR solo no abre, el sistema verifica que la persona esté activa y tenga una autorización aprobada y vigente. En la zona crítica usamos dos factores: algo que tienes, la tarjeta RFID, y algo que eres, el rostro. La captura muestra el lector QR real concediendo el acceso y encendiendo el LED verde que simula la puerta.");
  }

  // ============================================================ 5. Flujo
  {
    const s = content("D1 · FLUJO DE DECISIÓN", "Cualquier duda termina en acceso denegado", "Diseño");
    await fit(s, F("diagramas/flujo_decision_acceso.png"), M, 1.55, 12.1, 5.3, A(1, "zoom"));
    s.addNotes("Este es el flujo de la decisión. Rama izquierda, entrada principal: formato del QR, credencial activa y vigente, ingeniero activo, autorización vigente y dispositivo en línea; si todo pasa, LED verde cinco segundos y registro. Rama derecha, sala de servidores: tarjeta, vínculo, autorización y rostro. Cualquier 'no', error de red o firma inválida termina en denegado y queda en la bitácora: el sistema es fail-closed.");
  }

  // ============================================================ 6. Matriz de accesos
  pres.addSection({ title: "Matrices" });
  {
    const s = content("D2 · MATRIZ DE ACCESOS", "Menor privilegio por rol, zona y horario", "Matrices");
    const hdr = (t) => ({ text: t, options: { bold: true, color: HEX.white, fill: { color: HEX.navy } } });
    const ok = (t) => ({ text: t, options: { color: HEX.green } });
    const no = (t) => ({ text: t, options: { color: HEX.red } });
    const rows = [
      [hdr("Rol"), hdr("Z1 Entrada"), hdr("Z2 Sala de servidores"), hdr("Z3 Eléctrica"), hdr("Z4 Control")],
      [{ text: "Administrador de TI", options: { bold: true } }, ok("Sí · QR · 24/7"), ok("Sí · RFID + rostro · 24/7*"), ok("Sí · RFID · L–V 08–20"), ok("Sí · RFID · 24/7")],
      [{ text: "Ingeniero de red", options: { bold: true } }, ok("Sí · QR · L–S 07–22"), ok("Sí · RFID + rostro · L–V 08–20*"), no("No"), ok("Sí · RFID · L–V 08–20")],
      [{ text: "Personal de limpieza", options: { bold: true } }, ok("Sí · QR · L–S 06–09 y 18–21"), no("Solo escoltado*"), no("No"), no("No")],
      [{ text: "Proveedor", options: { bold: true } }, ok("Sí · QR temporal · L–V 09–18"), no("Solo escoltado*"), no("Solo escoltado"), no("No")],
    ];
    s.addTable(rows, { x: M, y: 1.75, w: 12.1, colW: [2.5, 2.5, 2.9, 2.1, 2.1], fontSize: 14, fontFace: "Calibri", color: HEX.ink, border: { type: "solid", pt: 1, color: HEX.line }, rowH: 0.62, valign: "middle", margin: 0.08, objectName: A(1, "wipe") });
    s.addText("* El horario lo aplica el sistema: cada acceso exige una solicitud aprobada (Registro 2) con su ventana de inicio y fin. Fuera de ella, el motor responde AUTH_NOT_STARTED o AUTH_EXPIRED.", { x: M, y: 5.25, w: 12.1, h: 0.75, fontSize: 13, italic: true, color: HEX.muted, margin: 0, isTextBox: true, objectName: A(2) });
    s.addNotes("La matriz de accesos tiene una fila por rol y una columna por zona; cada celda dice si puede entrar, con qué método y en qué horario. El horario no es solo papel: en el sistema cada acceso exige una solicitud aprobada con ventana de inicio y fin. Por eso, en la demo, la persona de limpieza entra a la recepción con su QR pero se le niega la sala de servidores.");
  }

  // ============================================================ 7. Sensores
  {
    const s = content("D3 · SENSORES Y ACCIONES", "Dos sensores reales con acción automática", "Matrices");
    const items = [
      [fa.FaThermometerHalf, "DHT11 · pasillo frío", "≥ 27 °C: ventilador encendido\n≥ 32 °C: buzzer intermitente\nHumedad fuera de 20–80 %: alarma", HEX.amber],
      [fa.FaUserSecret, "HC-SR04 · dentro de la sala", "Presencia ≤ 15 cm sin nadie autorizado dentro: LED rojo + buzzer 20 s + LCD «ALARMA»", HEX.red],
      [fa.FaFire, "Humo / inundación", "Representados. Real: VESDA por aspiración + gas limpio FM-200. El MQ-2 no sustituye a un detector certificado", HEX.muted],
    ];
    for (let i = 0; i < 3; i++) {
      const y = 1.7 + i * 1.6;
      card(s, M, y, 5.9, 1.45, { name: A(1 + i) });
      await iconCircle(s, items[i][0], M + 0.22, y + 0.35, 0.75, items[i][3], HEX.white, A(1 + i));
      s.addText(items[i][1], { x: M + 1.15, y: y + 0.12, w: 4.6, h: 0.4, fontSize: 15, bold: true, color: HEX.navy, margin: 0, isTextBox: true, objectName: A(1 + i) });
      s.addText(items[i][2], { x: M + 1.15, y: y + 0.52, w: 4.6, h: 0.85, fontSize: 12, color: HEX.ink, margin: 0, valign: "top", isTextBox: true, objectName: A(1 + i) });
    }
    await fit(s, F("capturas/dht11_panel.png"), 6.75, 1.7, 5.98, 4.3, A(4, "zoom"), { shadow: shadow() });
    s.addText("Panel en tiempo real: temperatura, humedad, ventilador y alarma", { x: 6.75, y: 6.15, w: 5.98, h: 0.3, fontSize: 11, color: HEX.muted, align: "center", margin: 0, isTextBox: true, objectName: A(4) });
    s.addNotes("Tenemos dos sensores reales. El DHT11, en el pasillo frío, es el sensor ambiental: a 27 grados enciende el ventilador, a 32 suena el buzzer, y si la humedad sale de 20 a 80 por ciento también avisa. El HC-SR04, dentro de la sala, detecta intrusos: si hay alguien y el sistema no tiene a nadie autorizado adentro, suena la alarma 20 segundos. Humo e inundación están representados; en un centro real usaríamos detección por aspiración certificada. A la derecha, el panel con las lecturas en vivo.");
  }

  // ============================================================ 8. Protocolos
  pres.addSection({ title: "Operación" });
  {
    const s = content("D4 · PROTOCOLO DE RESPUESTA", "Detectar, actuar, escalar y documentar", "Operación");
    const inc = [
      ["Temperatura alta", HEX.amber, ["DHT11 ≥ 27 °C → ventilador automático", "Operador revisa el CRAC 1", "≥ 32 °C: aviso al responsable y al proveedor", "15 min sin bajar: apagar cargas no críticas", "Contingencia: CRAC de respaldo, ATS y GEN 2N"]],
      ["Intrusión", HEX.red, ["HC-SR04 sin nadie autorizado → alarma 20 s", "Revisar CCTV 1–3 y la bitácora", "Avisar a vigilancia; nunca encerrar a nadie", "Revocar QR y tarjeta implicados", "Exportar bitácora y auditoría firmadas"]],
      ["Humo / incendio", HEX.muted, ["Detector por aspiración da la alarma", "Evacuar por la salida señalada", "30 s y descarga de gas limpio", "Cortar energía desde la sala eléctrica", "Conmutar al respaldo del Servidor de clientes"]],
    ];
    for (let i = 0; i < 3; i++) {
      const x = M + i * 4.1, w = 3.9;
      card(s, x, 1.7, w, 4.55, { name: A(1 + i) });
      s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: x + 0.25, y: 1.95, w: w - 0.5, h: 0.55, rectRadius: 0.1, fill: { color: inc[i][1] }, line: { color: inc[i][1] }, objectName: A(1 + i) });
      s.addText(`Incidente ${i + 1} · ${inc[i][0]}`, { x: x + 0.25, y: 1.95, w: w - 0.5, h: 0.55, fontSize: 15, bold: true, color: HEX.white, align: "center", valign: "middle", margin: 0, isTextBox: true, objectName: A(1 + i) });
      s.addText(inc[i][2].flatMap((t, k) => [{ text: `${k + 1}. `, options: { bold: true, color: inc[i][1] } }, { text: t, options: { breakLine: k < inc[i][2].length - 1 } }]), { x: x + 0.25, y: 2.7, w: w - 0.45, h: 3.4, fontSize: 13, color: HEX.ink, paraSpaceAfter: 7, valign: "top", margin: 0, isTextBox: true, objectName: A(1 + i) });
    }
    s.addText("Las personas siempre pueden salir: las salidas de emergencia con barra antipánico no dependen del control de acceso.", { x: M, y: 6.4, w: 12.1, h: 0.35, fontSize: 13, italic: true, color: HEX.teal, margin: 0, isTextBox: true, objectName: A(4) });
    s.addNotes("Definimos tres protocolos. Temperatura alta: el ventilador se enciende solo, el operador revisa el CRAC, si llega a crítica se escala y se enlaza con el plan de contingencia del Parcial 1: CRAC de respaldo y generadores 2N. Intrusión: alarma automática, revisión de cámaras y bitácora, aviso a vigilancia y revocación de credenciales; nunca se encierra a nadie. Incendio: evacuación, gas limpio y conmutación al respaldo.");
  }

  // ============================================================ 9. Bitácora
  {
    const s = content("D5 · BITÁCORA", "Cada intento y cada alarma quedan registrados", "Operación");
    await fit(s, F("capturas/bitacora.png"), M, 1.6, 7.9, 4.9, A(1, "zoom"), { shadow: shadow() });
    const stats = [["9", "accesos registrados en la demo", HEX.navy], ["4 / 5", "permitidos / denegados", HEX.teal], ["4", "alarmas de sensores", HEX.red]];
    for (let i = 0; i < 3; i++) {
      const y = 1.6 + i * 1.6;
      card(s, 8.85, y, 3.88, 1.4, { fill: HEX.soft, line: HEX.soft, noShadow: true, name: A(2 + i) });
      s.addText(stats[i][0], { x: 9.05, y: y + 0.12, w: 3.5, h: 0.75, fontSize: 40, bold: true, color: stats[i][2], margin: 0, isTextBox: true, objectName: A(2 + i) });
      s.addText(stats[i][1], { x: 9.05, y: y + 0.88, w: 3.5, h: 0.4, fontSize: 14, color: HEX.ink, margin: 0, isTextBox: true, objectName: A(2 + i) });
    }
    s.addText("Fecha y hora · persona o sensor · zona · método · resultado y motivo. La auditoría va encadenada con HMAC.", { x: M, y: 6.6, w: 12.1, h: 0.35, fontSize: 12, italic: true, color: HEX.muted, margin: 0, isTextBox: true, objectName: A(5) });
    s.addNotes("La bitácora registra fecha y hora, persona o sensor, zona, método y resultado con su motivo. En el ensayo de la demostración quedaron 9 accesos: 4 permitidos y 5 denegados, entre ellos un QR revocado, un proveedor sin autorización aprobada y la persona de limpieza intentando entrar a la sala de servidores. Además, 4 alarmas de sensores: temperatura alta, temperatura crítica, humedad e intrusión. La auditoría está encadenada con HMAC, así que una modificación se detecta.");
  }

  // ============================================================ 10. Nivel funcional
  {
    const s = content("NIVEL FUNCIONAL Y MATERIALES", "Hardware real conectado al sistema", "Operación");
    const bonus = [
      [fa.FaMicrochip, "+4 · Sensor real con acción real", "DHT11 → ventilador y buzzer; HC-SR04 → LED rojo y buzzer"],
      [fa.FaIdCard, "+4 · Lector real que permite o niega", "QR → LED verde; RFID + rostro → servo; todo a la bitácora"],
      [fa.FaDesktop, "+2 · Alerta en pantalla", "LCD 2004 en la puerta y panel web en tiempo real"],
    ];
    for (let i = 0; i < 3; i++) {
      const y = 1.7 + i * 1.45;
      await iconCircle(s, bonus[i][0], M, y + 0.1, 0.8, HEX.teal, HEX.white, A(1 + i));
      s.addText(bonus[i][1], { x: M + 1.05, y, w: 6.2, h: 0.45, fontSize: 17, bold: true, color: HEX.navy, margin: 0, isTextBox: true, objectName: A(1 + i) });
      s.addText(bonus[i][2], { x: M + 1.05, y: y + 0.48, w: 6.2, h: 0.6, fontSize: 14, color: HEX.ink, margin: 0, valign: "top", isTextBox: true, objectName: A(1 + i) });
    }
    card(s, 8.1, 1.7, 4.63, 4.3, { fill: HEX.navy, line: HEX.navy, name: A(4) });
    s.addText("D7 · Lista de materiales", { x: 8.35, y: 1.9, w: 4.1, h: 0.4, fontSize: 16, bold: true, color: HEX.cyan, margin: 0, isTextBox: true, objectName: A(4) });
    s.addText("≈ $1,020–1,370", { x: 8.35, y: 2.4, w: 4.1, h: 0.8, fontSize: 34, bold: true, color: HEX.white, margin: 0, isTextBox: true, objectName: A(4) });
    s.addText("MXN, costo estimado de referencia (por confirmar con cotización)", { x: 8.35, y: 3.2, w: 4.1, h: 0.55, fontSize: 12, color: HEX.ice, margin: 0, isTextBox: true, objectName: A(4) });
    s.addText("ESP32 · RC522 · DHT11 · HC-SR04 · SG90 · LCD 2004 · LEDs · buzzer · protoboard · webcam · foamboard", { x: 8.35, y: 3.9, w: 4.1, h: 1.0, fontSize: 13, color: HEX.white, margin: 0, valign: "top", isTextBox: true, objectName: A(4) });
    s.addText("D6 · Infografía: biometría con IA (en el documento)", { x: 8.35, y: 5.1, w: 4.1, h: 0.6, fontSize: 12, italic: true, color: HEX.ice, margin: 0, isTextBox: true, objectName: A(4) });
    s.addNotes("Implementamos el nivel funcional completo. Un sensor real dispara una acción real: el DHT11 enciende el ventilador. Un lector real permite o niega y registra: el QR enciende el LED verde y la tarjeta más rostro mueve el servo. Y la alerta llega a una pantalla: el LCD de la puerta y el panel web. El material cuesta aproximadamente entre mil y mil cuatrocientos pesos; son costos estimados que confirmamos con cotización. La infografía de biometría con IA está en el documento.");
  }

  // ============================================================ 11. Cierre / demo
  pres.addSection({ title: "Cierre" });
  {
    const s = pres.addSlide({ masterName: "DARK", sectionTitle: "Cierre" });
    s.addText("DEMOSTRACIÓN EN VIVO", { x: M, y: 0.9, w: 12, h: 0.4, fontSize: 13, bold: true, color: HEX.cyan, charSpacing: 2, margin: 0, isTextBox: true, objectName: A(1) });
    s.addText("Lo que van a ver ahora", { x: M, y: 1.35, w: 12, h: 0.8, fontSize: 36, bold: true, color: HEX.white, fontFace: "Arial", margin: 0, isTextBox: true, objectName: A(1) });
    const steps = [
      [fa.FaCheckCircle, "1 · Acceso autorizado", "QR → LED verde; RFID + rostro → servo y «Bienvenido»"],
      [fa.FaTimesCircle, "2 · Acceso denegado", "QR revocado o sin autorización → LED rojo y bitácora"],
      [fa.FaThermometerFull, "3 · Alarma ambiental", "Calor en el DHT11 → ventilador, alerta y protocolo 1"],
      [fa.FaQuestionCircle, "4 · Incidente sorpresa", "Lo resolvemos con el protocolo que corresponda"],
    ];
    for (let i = 0; i < 4; i++) {
      const x = M + i * 3.07, w = 2.87, y = 2.6;
      s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h: 2.9, rectRadius: 0.12, fill: { color: "13304F" }, line: { color: "21486F", width: 1 }, objectName: A(2 + i) });
      s.addImage({ data: await icon(steps[i][0], HEX.cyan), x: x + 0.25, y: y + 0.3, w: 0.6, h: 0.6, objectName: A(2 + i) });
      s.addText(steps[i][1], { x: x + 0.25, y: y + 1.05, w: w - 0.45, h: 0.45, fontSize: 16, bold: true, color: HEX.white, margin: 0, isTextBox: true, objectName: A(2 + i) });
      s.addText(steps[i][2], { x: x + 0.25, y: y + 1.55, w: w - 0.45, h: 1.2, fontSize: 13, color: HEX.ice, margin: 0, valign: "top", isTextBox: true, objectName: A(2 + i) });
    }
    s.addText("Si algo falla, explicamos qué se esperaba y qué pasó.  ·  Gracias — ¿preguntas?", { x: M, y: 6.0, w: 12.1, h: 0.45, fontSize: 15, color: HEX.white, margin: 0, isTextBox: true, objectName: A(6) });
    s.addNotes("Ahora pasamos a la demostración: primero un acceso autorizado completo, luego un acceso denegado que quedará en la bitácora, después calentamos el DHT11 para disparar el ventilador y aplicar el protocolo, y al final el incidente sorpresa que nos indique el profesor. Si algo falla, explicaremos qué se esperaba y qué pasó. Gracias.");
  }

  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("written", OUT);
})().catch((e) => { console.error(e); process.exit(1); });
