"""Diagrama de flujo de la decisión de acceso — Telecom Conecta (Proyecto Parcial 3).

(a) Entrada principal (QR)   (b) Sala de servidores — Servidor de clientes (RFID + rostro)
Uso: python3 flujo.py
"""
from common import (BG, FG, MUTED, arrow_marker, line, lines, path, poly, rect, text,
                    write_svg)

W, H = 1960, 1560
C_START, C_PROC, C_DEC = "#90a4ae", "#3d8bfd", "#ffb300"
C_OK, C_NO = "#2ecc71", "#ff4757"
C_EXIT = "#2ecc71"

out = []
add = out.append


def node_text(cx, cy, rows, size=14, fill=FG, weight="normal"):
    lh = size * 1.28
    y0 = cy - (len(rows) - 1) * lh / 2 + size * 0.36
    add(lines(cx, y0, rows, size=size, fill=fill, anchor="middle", halo=False, lh=lh,
              weight=weight))


def box(cx, cy, w, h, rows, color, fill="#111a26", rx=8, size=14, title_bold=False):
    add(rect(cx - w / 2, cy - h / 2, w, h, fill=fill, stroke=color, sw=2.5, rx=rx))
    node_text(cx, cy, rows, size=size, weight="bold" if title_bold else "normal")
    return (cx, cy, w, h)


def diamond(cx, cy, w, h, rows, size=13.5):
    add(poly([(cx, cy - h / 2), (cx + w / 2, cy), (cx, cy + h / 2), (cx - w / 2, cy)],
             fill="#221a05", stroke=C_DEC, sw=2.5))
    node_text(cx, cy, rows, size=size)
    return (cx, cy, w, h)


def arrow(x1, y1, x2, y2, color=FG, label=None, lx=0, ly=0, anchor="start", mk="arr"):
    add(line(x1, y1, x2, y2, stroke=color, sw=2.2, marker=mk))
    if label:
        add(text(x1 + lx, y1 + ly, label, size=13, fill=color, weight="bold", anchor=anchor))


def column(cx, bus_x, title, subtitle, color, steps, ok_rows, deny_rows, top=190, gap=34):
    """Vertical flow: steps are ('start'|'proc'|'dec', rows, h). 'No' goes to bus_x."""
    add(rect(cx - 330, top - 62, bus_x - cx + 330 + 150, 50, fill="#111823", stroke=color, sw=2,
             rx=10))
    add(text(cx - 312, top - 31, title, size=19, fill=color, weight="bold", halo=False))
    add(text(bus_x + 135, top - 31, subtitle, size=13, fill=MUTED, anchor="end", halo=False))
    y = top
    prev_bottom = None
    no_ys = []
    for kind, rows, h in steps:
        cy = y + h / 2
        if prev_bottom is not None:
            arrow(cx, prev_bottom, cx, y - 2, label="Sí" if prev_kind == "dec" else None,
                  lx=10, ly=20)
        if kind == "start":
            box(cx, cy, 440, h, rows, C_START, fill="#1b2430", rx=h / 2, size=14)
        elif kind == "proc":
            box(cx, cy, 440, h, rows, C_PROC, fill="#0f1f38", size=14)
        else:
            diamond(cx, cy, 400, h, rows)
            add(line(cx + 200, cy, bus_x, cy, stroke=C_NO, sw=2.2))
            add(text(cx + 212, cy - 8, "No", size=13, fill=C_NO, weight="bold"))
            no_ys.append(cy)
        prev_bottom, prev_kind = y + h, kind
        y += h + gap
    # OK terminal
    ok_h = 26 * len(ok_rows) + 26
    arrow(cx, prev_bottom, cx, y - 2, label="Sí", lx=10, ly=20)
    box(cx, y + ok_h / 2, 440, ok_h, ok_rows, C_OK, fill="#0f2a1a", size=14)
    ok_bottom = y + ok_h
    # deny bus + terminal
    deny_h = 24 * len(deny_rows) + 26
    deny_cy = no_ys[-1] + 150 + deny_h / 2
    add(line(bus_x, no_ys[0], bus_x, deny_cy - deny_h / 2 - 2, stroke=C_NO, sw=2.6, marker="arrNo"))
    for ny in no_ys:
        add(f'<circle cx="{bus_x}" cy="{ny}" r="4" fill="{C_NO}"/>')
    box(bus_x, deny_cy, 300, deny_h, deny_rows, C_NO, fill="#2a0f14", size=13)
    return ok_bottom, deny_cy + deny_h / 2


# ---------------------------------------------------------------- header
add(text(60, 56, "Telecom Conecta — Flujo de decisión de acceso", size=30, weight="bold"))
add(text(60, 88, "Proyecto Parcial 3 · Zona crítica: Servidor de clientes · Fail-closed: ante "
         "cualquier error, duda o tiempo agotado la puerta permanece cerrada", size=15, fill=MUTED))
add(text(W - 50, 56, "Fecha: 2026-11-17", size=17, anchor="end", weight="bold"))
add(text(W - 50, 84, "Solo el Registro 2 (autorizaciones) concede acceso", size=13.5,
         anchor="end", fill="#ffd27a"))
add(text(W - 50, 104, "El Registro 1 (alta de ingenieros y rostros) nunca lo hace", size=13.5,
         anchor="end", fill="#ffd27a"))

# ---------------------------------------------------------------- (a) main entrance
A_CX, A_BUS = 340, 760
a_ok_bottom, a_deny_bottom = column(
    A_CX, A_BUS, "(a) Entrada principal — Zona Z1", "Lector QR (webcam) + LED verde", "#4dd0e1",
    [
        ("start", ["Persona en la entrada principal", "escanea su código QR en la webcam (A1)"], 70),
        ("dec", ["¿Formato del QR", "válido?"], 112),
        ("dec", ["¿Credencial activa", "y vigente?"], 112),
        ("dec", ["¿Ingeniero activo?"], 112),
        ("dec", ["¿Autorización (Registro 2)", "APROBADA y vigente", "ahora?"], 128),
        ("dec", ["¿Dispositivo de la", "entrada en línea?"], 112),
    ],
    ["PERMITIDO", "LED verde 5 s = puerta abierta (A2)", "LCD «ACCESO QR OK» + nombre",
     "Bitácora: PERMITIDO · QR · Z1"],
    ["DENEGADO", "LED rojo parpadea 3 veces", "y pitido corto del buzzer", "LCD «QR DENEGADO»",
     "Bitácora: DENEGADO + motivo", "Puerta cerrada"],
)

# ---------------------------------------------------------------- (b) server room
B_CX, B_BUS = 1330, 1750
b_ok_bottom, b_deny_bottom = column(
    B_CX, B_BUS, "(b) Sala de servidores — Zona Z2 (nivel 3)", "RFID + rostro + servo",
    "#ff3df0",
    [
        ("start", ["Ingeniero acerca su tarjeta al", "lector RFID RC522 (A3) de la puerta"], 70),
        ("dec", ["¿Tarjeta registrada", "y ACTIVA?"], 112),
        ("dec", ["¿Vinculada a un", "ingeniero activo?"], 112),
        ("dec", ["¿Autorización Registro 2", "vigente ahora para Z2?"], 112),
        ("proc", ["Kiosco facial (A4): captura 5 cuadros,", "verificación 1:1 + prueba de vida"],
         70),
        ("dec", ["¿≥ 3 de 5 cuadros con", "similitud ≥ 0.45", "y liveness OK?"], 128),
        ("dec", ["¿Presencia (HC-SR04) y", "Registro 2 aún vigente?"], 112),
    ],
    ["PERMITIDO", "Servo SG90 abre la cerradura (A5)", "LCD «ACCESO CONCEDIDO»",
     "Bitácora: PERMITIDO · RFID+ROSTRO"],
    ["DENEGADO", "Servo permanece cerrado", "LED rojo + LCD «DENEGADO»",
     "Bitácora: DENEGADO + motivo", "También: error de red, firma", "HMAC inválida o tiempo agotado"],
)

# ---------------------------------------------------------------- exit panel (below b)
ex_y = max(b_ok_bottom, b_deny_bottom) + 40
ex_x, ex_w = B_CX - 330, B_BUS + 150 - (B_CX - 330)
ex_h = 214
add(rect(ex_x, ex_y, ex_w, ex_h, fill="#0f2a1a", stroke=C_EXIT, sw=2.5, rx=10))
add(text(ex_x + 18, ex_y + 32, "Salida de la sala de servidores — nunca se atrapa a nadie",
         size=17, fill="#a8f0c0", weight="bold", halo=False))
exit_rows = [
    ("Botón de salida interior (A6):", "el backend confirma que hay alguien dentro → servo abre"
     " + bitácora SALIDA."),
    ("Segunda pasada de tarjeta:", "rostro 1:1 en el kiosco, sin exigir Registro 2 → aunque la"),
    ("", "autorización haya vencido o se haya revocado, la persona puede salir (alerta CRÍTICA)."),
    ("Sin conexión o falla:", "el servo queda cerrado (el botón tampoco abre); las salidas"),
    ("", "de emergencia con barra antipánico siempre están libres y señalizadas."),
]
yy = ex_y + 66
for head, rest in exit_rows:
    if head:
        add(text(ex_x + 18, yy, head, size=14, fill="#a8f0c0", weight="bold", halo=False))
    add(text(ex_x + 268, yy, rest, size=14, fill=FG, halo=False))
    yy += 30

# arrow from OK (b) to exit panel
add(line(B_CX, b_ok_bottom, B_CX, ex_y - 2, stroke=C_EXIT, sw=2.2, dash="7 5", marker="arrOk"))
add(text(B_CX + 10, b_ok_bottom + 26, "al terminar el trabajo", size=12.5, fill="#a8f0c0"))

# ---------------------------------------------------------------- legend (below a)
lg_y = max(a_ok_bottom, a_deny_bottom) + 40
lg_x, lg_w = A_CX - 330, A_BUS + 150 - (A_CX - 330)
add(rect(lg_x, lg_y, lg_w, ex_h, fill="#111823", stroke="#2c3a4a", sw=1.5, rx=10))
add(text(lg_x + 18, lg_y + 32, "Simbología", size=17, weight="bold", halo=False))
items = [
    (lambda x, y: add(rect(x, y - 13, 56, 26, fill="#1b2430", stroke=C_START, sw=2, rx=13)),
     "Inicio (evento del usuario)"),
    (lambda x, y: add(rect(x, y - 13, 56, 26, fill="#0f1f38", stroke=C_PROC, sw=2, rx=4)),
     "Proceso"),
    (lambda x, y: add(poly([(x + 28, y - 15), (x + 56, y), (x + 28, y + 15), (x, y)],
                           fill="#221a05", stroke=C_DEC, sw=2)), "Decisión (Sí ↓ / No →)"),
    (lambda x, y: add(rect(x, y - 13, 56, 26, fill="#0f2a1a", stroke=C_OK, sw=2, rx=4)),
     "Resultado PERMITIDO"),
    (lambda x, y: add(rect(x, y - 13, 56, 26, fill="#2a0f14", stroke=C_NO, sw=2, rx=4)),
     "Resultado DENEGADO (todo «No» llega aquí)"),
]
for i, (draw, lab) in enumerate(items):
    c, r = divmod(i, 3)
    x = lg_x + 18 + c * 300
    y = lg_y + 70 + r * 44
    draw(x, y)
    add(text(x + 70, y + 5, lab, size=13.5, halo=False))
add(text(lg_x + 318, lg_y + 158, "Cada intento, permitido o denegado, queda en la bitácora",
         size=13, fill=MUTED, halo=False))
add(text(lg_x + 318, lg_y + 178, "con fecha y hora (UTC), persona, zona, método y resultado.",
         size=13, fill=MUTED, halo=False))

H_final = int(max(ex_y, lg_y) + ex_h + 40)
defs = (arrow_marker("arr", FG, 11) + arrow_marker("arrNo", C_NO, 12)
        + arrow_marker("arrOk", C_EXIT, 12))
write_svg("flujo_decision_acceso", W, H_final, "\n".join(out), defs, scale=1.6)
