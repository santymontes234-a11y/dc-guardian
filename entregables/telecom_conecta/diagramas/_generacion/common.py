"""Shared SVG helpers and PNG rendering (headless Chromium) for the Telecom Conecta diagrams."""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

FONT = "DejaVu Sans, Noto Sans, Liberation Sans, Arial, sans-serif"
OUT_DIR = Path(__file__).resolve().parent.parent

BG = "#0d1117"
FG = "#e6edf3"
MUTED = "#9aa7b4"


def esc(s: str) -> str:
    return escape(str(s))


def text(x, y, s, size=13, fill=FG, anchor="start", weight="normal", halo=True,
         rotate=None, style="", family=FONT):
    """Single text line. `halo` draws a background-colored outline for legibility over the grid."""
    rot = f' transform="rotate({rotate} {x:.1f} {y:.1f})"' if rotate is not None else ""
    h = (f' stroke="{BG}" stroke-width="3.2" stroke-linejoin="round" paint-order="stroke"'
         if halo else "")
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{family}" font-size="{size}" '
            f'fill="{fill}" text-anchor="{anchor}" font-weight="{weight}"{h}{rot} '
            f'style="{style}">{esc(s)}</text>')


def lines(x, y, rows, size=13, lh=None, **kw):
    lh = lh or size * 1.25
    return "".join(text(x, y + i * lh, r, size=size, **kw) for i, r in enumerate(rows))


def rect(x, y, w, h, fill="none", stroke="none", sw=1, rx=0, dash=None, opacity=1, extra=""):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d} opacity="{opacity}" {extra}/>')


def line(x1, y1, x2, y2, stroke=FG, sw=1, dash=None, marker=None, opacity=1, cap="butt"):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    m = f' marker-end="url(#{marker})"' if marker else ""
    return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{stroke}" '
            f'stroke-width="{sw}"{d}{m} opacity="{opacity}" stroke-linecap="{cap}"/>')


def path(d, stroke=FG, sw=1, fill="none", dash=None, marker=None, opacity=1, extra=""):
    da = f' stroke-dasharray="{dash}"' if dash else ""
    m = f' marker-end="url(#{marker})"' if marker else ""
    return (f'<path d="{d}" stroke="{stroke}" stroke-width="{sw}" fill="{fill}"{da}{m} '
            f'opacity="{opacity}" stroke-linejoin="round" stroke-linecap="round" {extra}/>')


def circle(cx, cy, r, fill="none", stroke="none", sw=1, opacity=1, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{fill}" stroke="{stroke}" '
            f'stroke-width="{sw}"{d} opacity="{opacity}"/>')


def poly(pts, fill="none", stroke="none", sw=1, opacity=1):
    p = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    return (f'<polygon points="{p}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" '
            f'opacity="{opacity}" stroke-linejoin="round"/>')


def arrow_marker(mid, color, size=8):
    return (f'<marker id="{mid}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="{size}" '
            f'markerHeight="{size}" orient="auto-start-reverse" markerUnits="userSpaceOnUse">'
            f'<path d="M0,0 L10,5 L0,10 z" fill="{color}"/></marker>')


def svg_doc(w, h, body, defs=""):
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}" font-family="{FONT}">\n<defs>{defs}</defs>\n'
            f'{rect(0, 0, w, h, fill=BG)}\n{body}\n</svg>\n')


def find_chromium():
    for name in ("chromium", "chromium-browser", "google-chrome"):
        p = shutil.which(name)
        if p:
            return p
    base = Path.home() / ".cache" / "ms-playwright"
    for cand in sorted(base.glob("chromium-*/chrome-linux*/chrome"), reverse=True):
        return str(cand)
    raise SystemExit("No Chromium found to rasterize the SVG")


def render_png(svg_path: Path, png_path: Path, w: int, h: int, scale: float):
    """Rasterize an SVG with headless Chromium at `scale` device pixels per SVG unit."""
    chrome = find_chromium()
    with tempfile.TemporaryDirectory() as tmp:
        html = Path(tmp) / "page.html"
        html.write_text(
            f'<!doctype html><meta charset="utf-8"><style>html,body{{margin:0;background:{BG}}}'
            f'img{{display:block;width:{w}px;height:{h}px}}</style>'
            f'<img src="file://{svg_path}">', encoding="utf-8")
        subprocess.run(
            [chrome, "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
             f"--force-device-scale-factor={scale}", f"--window-size={w},{h}",
             "--virtual-time-budget=2000", f"--user-data-dir={tmp}/profile",
             f"--screenshot={png_path}", f"file://{html}"],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("PNG:", png_path)


def write_svg(name: str, w: int, h: int, body: str, defs: str = "", scale: float = 2.0):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    svg_path = OUT_DIR / f"{name}.svg"
    svg_path.write_text(svg_doc(w, h, body, defs), encoding="utf-8")
    print("SVG:", svg_path)
    render_png(svg_path, OUT_DIR / f"{name}.png", w, h, scale)
