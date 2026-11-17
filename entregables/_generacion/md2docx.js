// Convierte entregables/reporte_tecnico.md en un DOCX formal (docx + marked).
const fs = require("fs");
const path = require("path");
const sharp = require("sharp");
const { marked } = require("marked");
const D = require("docx");

const SRC = process.argv[2], OUT = process.argv[3];
const BASE = path.dirname(SRC);
const NAVY = "0B1B33", BLUE = "1F5FBF", CYAN = "2BB3C0", MUTED = "5B6573", LINE = "C9D1DC", SOFT = "EEF3FB";
const FONT = "Arial", HFONT = "Arial";
const PAGE_W = 11906, PAGE_H = 16838, MARGIN = 1134, CONTENT = PAGE_W - 2 * MARGIN; // A4, 2 cm

const decode = (s) => s.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");

function runs(tokens, base = {}) {
  const out = [];
  for (const t of tokens || []) {
    switch (t.type) {
      case "text":
        if (t.tokens) out.push(...runs(t.tokens, base)); else out.push(new D.TextRun({ text: decode(t.text), ...base }));
        break;
      case "strong": out.push(...runs(t.tokens, { ...base, bold: true })); break;
      case "em": out.push(...runs(t.tokens, { ...base, italics: true })); break;
      case "codespan": out.push(new D.TextRun({ text: decode(t.text), ...base, font: "Courier New", size: (base.size || 21) - 2, color: "1C3D73" })); break;
      case "link":
        out.push(new D.ExternalHyperlink({ link: t.href, children: [new D.TextRun({ text: decode(t.text), ...base, color: BLUE, underline: {} })] }));
        break;
      case "br": out.push(new D.TextRun({ break: 1 })); break;
      case "html": break;
      case "escape": out.push(new D.TextRun({ text: decode(t.text), ...base })); break;
      default: if (t.text) out.push(new D.TextRun({ text: decode(t.text), ...base }));
    }
  }
  return out;
}
const plain = (tokens) => (tokens || []).map((t) => (t.tokens ? plain(t.tokens) : decode(t.text || ""))).join("");

let figN = 0;
const numberingRefs = [];
async function image(tok) {
  const file = path.join(BASE, tok.href);
  const buf = fs.readFileSync(file);
  const meta = await sharp(buf).metadata();
  const maxW = 6.5 * 96, maxH = 8.2 * 96; // px at 96 dpi
  let w = maxW, h = (meta.height / meta.width) * w;
  if (h > maxH) { h = maxH; w = (meta.width / meta.height) * h; }
  figN++;
  return [
    new D.Paragraph({ alignment: D.AlignmentType.CENTER, spacing: { before: 120, after: 60 }, keepNext: true,
      children: [new D.ImageRun({ type: "png", data: buf, transformation: { width: Math.round(w), height: Math.round(h) }, altText: { title: tok.text, description: tok.text, name: path.basename(file) } })] }),
    new D.Paragraph({ alignment: D.AlignmentType.CENTER, spacing: { after: 200 },
      children: [new D.TextRun({ text: `Figura ${figN}. `, bold: true, size: 18, color: MUTED }), new D.TextRun({ text: tok.text, italics: true, size: 18, color: MUTED })] }),
  ];
}

function table(tok) {
  const ncol = tok.header.length;
  const lens = tok.header.map((h, i) => Math.max(plain(h.tokens).length, ...tok.rows.map((r) => Math.min(plain(r[i].tokens).length, 60))));
  const longest = tok.header.map((h, i) => Math.max(...[plain(h.tokens), ...tok.rows.map((r) => plain(r[i].tokens))].flatMap((s) => s.split(/\s+/)).map((w) => w.length)));
  const weights = lens.map((l, i) => Math.max(8, Math.sqrt(l) * 10, longest[i] * 3.2));
  const sum = weights.reduce((a, b) => a + b, 0);
  const widths = weights.map((w) => Math.floor((w / sum) * CONTENT));
  widths[widths.length - 1] += CONTENT - widths.reduce((a, b) => a + b, 0);
  const size = ncol >= 5 ? 16 : 19;
  const border = { style: D.BorderStyle.SINGLE, size: 4, color: LINE };
  const borders = { top: border, bottom: border, left: border, right: border };
  const cell = (tokens, i, header, zebra) => new D.TableCell({
    width: { size: widths[i], type: D.WidthType.DXA }, borders,
    shading: header ? { type: D.ShadingType.CLEAR, color: "auto", fill: NAVY } : zebra ? { type: D.ShadingType.CLEAR, color: "auto", fill: "F5F7FA" } : undefined,
    margins: { top: 50, bottom: 50, left: 90, right: 90 },
    children: [new D.Paragraph({ spacing: { before: 0, after: 0 }, children: runs(tokens, header ? { bold: true, color: "FFFFFF", size } : { size }) })],
  });
  return new D.Table({
    width: { size: CONTENT, type: D.WidthType.DXA }, columnWidths: widths,
    rows: [new D.TableRow({ tableHeader: true, cantSplit: true, children: tok.header.map((h, i) => cell(h.tokens, i, true)) }),
      ...tok.rows.map((r, k) => new D.TableRow({ cantSplit: true, children: r.map((c, i) => cell(c.tokens, i, false, k % 2 === 1)) }))],
  });
}

(async () => {
  const md = fs.readFileSync(SRC, "utf8");
  const tokens = marked.lexer(md);
  const body = [];
  const headings = tokens.filter((t) => t.type === "heading" && t.depth === 2 && plain(t.tokens) !== "Índice").map((t) => plain(t.tokens));
  let i = 0;

  // ---------- portada (H1 + línea de subtítulo + tabla de datos + nota)
  const h1 = tokens.find((t) => t.type === "heading" && t.depth === 1);
  const coverTable = tokens.find((t) => t.type === "table");
  const cover = [
    new D.Paragraph({ spacing: { before: 2200, after: 120 }, children: [new D.TextRun({ text: "REPORTE TÉCNICO Y FUNCIONAL", bold: true, color: CYAN, size: 22, font: HFONT, characterSpacing: 40 })] }),
    new D.Paragraph({ spacing: { after: 120 }, children: [new D.TextRun({ text: "DC Guardian", bold: true, size: 72, color: NAVY, font: HFONT })] }),
    new D.Paragraph({ spacing: { after: 600 }, children: [new D.TextRun({ text: "Sistema académico de control de acceso inteligente a un Data Center", size: 30, color: MUTED })] }),
    table(coverTable),
    new D.Paragraph({ spacing: { before: 600 }, children: [new D.TextRun({ text: "Proyecto académico. Los nombres, áreas y personas de los datos de demostración son ficticios.", italics: true, size: 18, color: MUTED })] }),
    new D.Paragraph({ children: [new D.PageBreak()] }),
  ];
  body.push(...cover);
  // skip tokens until after the cover table
  i = tokens.indexOf(coverTable) + 1;

  for (; i < tokens.length; i++) {
    const t = tokens[i];
    if (t.type === "space" || t.type === "html" && !t.text.includes("INDICE")) continue;
    if (t.type === "html" && t.text.includes("INDICE")) {
      headings.forEach((h) => body.push(new D.Paragraph({ spacing: { after: 60 }, indent: { left: 200 }, children: [new D.TextRun({ text: h, size: 22, color: NAVY })] })));
      body.push(new D.Paragraph({ children: [new D.PageBreak()] }));
      continue;
    }
    switch (t.type) {
      case "heading": {
        const text = plain(t.tokens);
        if (t.depth === 2) {
          const pageBreak = text !== "Índice" && !/^1\. /.test(text);
          body.push(new D.Paragraph({ heading: D.HeadingLevel.HEADING_1, pageBreakBefore: pageBreak && /^(\d+\.|Anexo)/.test(text) && !/^(5|7|10|12|14|17|18|20)\. /.test(text) ? false : false, children: [new D.TextRun(text)] }));
        } else if (t.depth === 3) body.push(new D.Paragraph({ heading: D.HeadingLevel.HEADING_2, children: [new D.TextRun(text)] }));
        else body.push(new D.Paragraph({ heading: D.HeadingLevel.HEADING_3, children: [new D.TextRun(text)] }));
        break;
      }
      case "paragraph": {
        const imgs = (t.tokens || []).filter((x) => x.type === "image");
        if (imgs.length) { for (const im of imgs) body.push(...(await image(im))); break; }
        body.push(new D.Paragraph({ spacing: { after: 140, line: 288 }, alignment: D.AlignmentType.JUSTIFIED, children: runs(t.tokens) }));
        break;
      }
      case "list":
        t.items.forEach((it) => {
          const inner = it.tokens.flatMap((x) => (x.type === "text" && x.tokens ? x.tokens : x.type === "text" ? [x] : x.tokens || []));
          body.push(new D.Paragraph({ numbering: { reference: t.ordered ? "num" + i : "bullets", level: 0 }, spacing: { after: 80, line: 276 }, children: runs(inner) }));
        });
        if (t.ordered) numberingRefs.push("num" + i);
        break;
      case "table":
        body.push(table(t));
        body.push(new D.Paragraph({ spacing: { after: 160 }, children: [] }));
        break;
      case "blockquote": {
        const inner = t.tokens.filter((x) => x.type === "paragraph");
        inner.forEach((p) => body.push(new D.Paragraph({ shading: { type: D.ShadingType.CLEAR, color: "auto", fill: SOFT }, indent: { left: 200, right: 200 }, spacing: { before: 80, after: 160, line: 288 },
          border: { top: { style: D.BorderStyle.SINGLE, size: 4, color: "B9CCEB", space: 6 }, bottom: { style: D.BorderStyle.SINGLE, size: 4, color: "B9CCEB", space: 6 }, left: { style: D.BorderStyle.SINGLE, size: 4, color: "B9CCEB", space: 8 }, right: { style: D.BorderStyle.SINGLE, size: 4, color: "B9CCEB", space: 8 } },
          children: runs(p.tokens, { size: 20 }) })));
        break;
      }
      case "code":
        t.text.split("\n").forEach((l) => body.push(new D.Paragraph({ shading: { type: D.ShadingType.CLEAR, color: "auto", fill: "F3F4F6" }, spacing: { after: 0 }, children: [new D.TextRun({ text: l, font: "Courier New", size: 18 })] })));
        break;
      case "hr": break;
      default: console.warn("token sin tratar:", t.type);
    }
  }

  const doc = new D.Document({
    creator: "Santiago Martín Montes Rubio",
    title: "DC Guardian — Reporte técnico y funcional",
    description: "Reporte técnico y funcional del proyecto DC Guardian",
    styles: {
      default: { document: { run: { font: FONT, size: 20, color: "1C2430" } } },
      paragraphStyles: [
        { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { font: HFONT, size: 32, bold: true, color: NAVY }, paragraph: { spacing: { before: 420, after: 160 }, keepNext: true, outlineLevel: 0 } },
        { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, run: { font: HFONT, size: 25, bold: true, color: BLUE }, paragraph: { spacing: { before: 260, after: 120 }, keepNext: true, outlineLevel: 1 } },
        { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true, run: { font: HFONT, size: 22, bold: true, color: NAVY }, paragraph: { spacing: { before: 200, after: 80 }, keepNext: true, outlineLevel: 2 } },
      ],
    },
    numbering: { config: [
      { reference: "bullets", levels: [{ level: 0, format: D.LevelFormat.BULLET, text: "•", alignment: D.AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 270 } } } }] },
      ...numberingRefs.map((r) => ({ reference: r, levels: [{ level: 0, format: D.LevelFormat.DECIMAL, text: "%1.", alignment: D.AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 300 } } } }] })),
    ] },
    sections: [{
      properties: { page: { size: { width: PAGE_W, height: PAGE_H }, margin: { top: MARGIN, bottom: MARGIN, left: MARGIN, right: MARGIN } }, titlePage: true },
      headers: { default: new D.Header({ children: [new D.Paragraph({ alignment: D.AlignmentType.RIGHT, children: [new D.TextRun({ text: "DC Guardian · Reporte técnico y funcional", size: 16, color: MUTED })] })] }), first: new D.Header({ children: [] }) },
      footers: { default: new D.Footer({ children: [new D.Paragraph({ alignment: D.AlignmentType.CENTER, children: [new D.TextRun({ text: "Página ", size: 16, color: MUTED }), new D.TextRun({ children: [D.PageNumber.CURRENT], size: 16, color: MUTED }), new D.TextRun({ text: " de ", size: 16, color: MUTED }), new D.TextRun({ children: [D.PageNumber.TOTAL_PAGES], size: 16, color: MUTED })] })] }), first: new D.Footer({ children: [] }) },
      children: body,
    }],
  });
  fs.writeFileSync(OUT, await D.Packer.toBuffer(doc));
  console.log("written", OUT, "figuras:", figN);
})().catch((e) => { console.error(e); process.exit(1); });
