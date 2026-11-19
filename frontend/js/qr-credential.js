// Credencial QR imprimible de Telecom Conecta (contrato QR + DHT11 §2).
//   import { drawCredential, credentialBlob } from "/js/qr-credential.js";
//   const canvas = drawCredential({ qrText, name, position, engineerCode, prefix, issuedAt, expiresAt, singleUse });
// Todo se dibuja en un <canvas> con fillText (sin HTML: el texto del servidor no puede inyectar
// marcado). El QR se genera en el navegador con qrcode-generator (vendorizado, sin red).
import qrcode from "/vendor/qrcode-generator-2.0.4/qrcode.mjs";
import { COMPANY, PRODUCT } from "/js/brand.js";

const W = 640;
const H = 980;
const BRAND = "#1f5fbf";

function fitText(ctx, text, maxWidth, size, weight = "700", family = "system-ui, sans-serif") {
  let s = size;
  do {
    ctx.font = `${weight} ${s}px ${family}`;
    if (ctx.measureText(text).width <= maxWidth) break;
    s -= 1;
  } while (s > 12);
  return s;
}

function fmtDay(iso) {
  if (!iso) return null;
  return new Date(iso).toLocaleDateString("es", { day: "2-digit", month: "long", year: "numeric" });
}

function fmtDayTime(iso) {
  if (!iso) return null;
  return new Date(iso).toLocaleString("es", { day: "2-digit", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** Matriz del QR (corrección de errores M, versión automática). */
export function qrMatrix(text) {
  const qr = qrcode(0, "M");
  qr.addData(text, "Byte");
  qr.make();
  const n = qr.getModuleCount();
  return { n, dark: (r, c) => qr.isDark(r, c) };
}

export function drawCredential({ qrText, name, position, engineerCode, prefix, issuedAt, expiresAt, singleUse = false }) {
  const canvas = document.createElement("canvas");
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext("2d");
  ctx.textAlign = "center";
  ctx.textBaseline = "alphabetic";

  // Fondo y borde
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, W, H);
  ctx.strokeStyle = "#c9d1dc";
  ctx.lineWidth = 4;
  ctx.strokeRect(2, 2, W - 4, H - 4);

  // Banda de la empresa
  ctx.fillStyle = BRAND;
  ctx.fillRect(0, 0, W, 150);
  ctx.fillStyle = "#ffffff";
  fitText(ctx, COMPANY, W - 60, 48, "800");
  ctx.fillText(COMPANY, W / 2, 78);
  ctx.font = "500 22px system-ui, sans-serif";
  ctx.fillText("Credencial de acceso · Entrada principal", W / 2, 118);

  // Titular
  ctx.fillStyle = "#1c2430";
  fitText(ctx, name || "—", W - 60, 38, "700");
  ctx.fillText(name || "—", W / 2, 210);
  ctx.fillStyle = "#3d4757";
  fitText(ctx, position || "—", W - 60, 26, "500");
  ctx.fillText(position || "—", W / 2, 250);
  if (engineerCode) {
    ctx.font = "500 20px ui-monospace, Menlo, monospace";
    ctx.fillStyle = "#5b6573";
    ctx.fillText(engineerCode, W / 2, 282);
  }

  // Código QR con zona de silencio de 4 módulos
  const { n, dark } = qrMatrix(qrText);
  const box = 420;
  const cell = Math.floor(box / (n + 8));
  const size = cell * (n + 8);
  const x0 = Math.round((W - size) / 2);
  const y0 = 305;
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(x0, y0, size, size);
  ctx.fillStyle = "#000000";
  for (let r = 0; r < n; r += 1) {
    for (let c = 0; c < n; c += 1) {
      if (dark(r, c)) ctx.fillRect(x0 + (c + 4) * cell, y0 + (r + 4) * cell, cell, cell);
    }
  }

  // Datos de la credencial
  let y = y0 + size + 50;
  ctx.fillStyle = "#1c2430";
  ctx.font = "600 24px ui-monospace, Menlo, monospace";
  ctx.fillText(`Prefijo: ${prefix ?? "—"}`, W / 2, y);
  y += 38;
  ctx.font = "400 21px system-ui, sans-serif";
  ctx.fillStyle = "#3d4757";
  ctx.fillText(`Emitida: ${fmtDay(issuedAt) ?? "—"}`, W / 2, y);
  y += 32;
  ctx.fillText(`Vence: ${fmtDayTime(expiresAt) ?? "sin vencimiento"}`, W / 2, y);
  if (singleUse) {
    y += 34;
    ctx.fillStyle = "#9a3412";
    ctx.font = "700 21px system-ui, sans-serif";
    ctx.fillText("PASE DE UN SOLO USO", W / 2, y);
  }

  // Pie
  ctx.fillStyle = "#eef0f3";
  ctx.fillRect(4, H - 70, W - 8, 66);
  ctx.fillStyle = "#5b6573";
  ctx.font = "500 17px system-ui, sans-serif";
  ctx.fillText(`${PRODUCT} · Uso personal e intransferible`, W / 2, H - 42);
  ctx.font = "400 15px system-ui, sans-serif";
  ctx.fillText("El acceso requiere además una autorización aprobada y vigente.", W / 2, H - 18);
  return canvas;
}

export function credentialBlob(canvas) {
  return new Promise((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("No se pudo generar la imagen"))), "image/png"));
}
