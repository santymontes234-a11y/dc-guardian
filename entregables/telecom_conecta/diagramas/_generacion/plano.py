"""Plano de seguridad del centro de datos — Telecom Conecta (Proyecto Parcial 3).

Redibuja el plano del Parcial 1 (sala 10 m × 8 m) y agrega zonas de seguridad,
dispositivos de acceso, sensores, alarmas/actuadores y rutas de evacuación.
Uso: python3 plano.py
"""
from common import (BG, FG, MUTED, arrow_marker, circle, esc, line, lines, path, poly,
                    rect, text, write_svg)

# ---------------------------------------------------------------- geometry
S = 100            # SVG units per metre
OX, OY = 110, 175  # room origin (top-left corner of the 10 m × 8 m hall)
W, H = 2060, 1500


def X(m):
    return OX + m * S


def Y(m):
    return OY + m * S


# ---------------------------------------------------------------- palette
C_HOT, C_COLD = "#c0392b", "#138a8a"
C_RACK, C_RACK_EDGE = "#2b3440", "#8fa3b8"
C_WALL, C_PART = "#d7dee5", "#8d9aa6"
C_EXIT = "#2ecc71"
C_ACC, C_SEN, C_ALM, C_CTL = "#3d8bfd", "#ffb300", "#ff4757", "#b0bec5"
C_CRAC, C_UPS, C_ELEC, C_CTRL = "#4f83b8", "#e67e22", "#e67e22", "#9b59b6"
C_EXT = "#e74c3c"
Z_COL = {"Z1": "#4dd0e1", "Z2": "#ff3df0", "Z3": "#ff9f43", "Z4": "#c39bff", "Z0": "#90a4ae"}
C_CLIENT = "#ff3df0"

out = []
add = out.append


def zone_tag(x, y, code, label, color, anchor="start", size=13):
    """Pill with zone code + label."""
    w_code = 34
    w_lab = len(label) * size * 0.58 + 14
    total = w_code + w_lab
    x0 = x if anchor == "start" else x - total
    add(rect(x0, y - 15, total, 22, fill=BG, stroke=color, sw=2, rx=11))
    add(rect(x0, y - 15, w_code, 22, fill=color, rx=11))
    add(text(x0 + w_code / 2, y + 1, code, size=size, fill=BG, anchor="middle", weight="bold",
             halo=False))
    add(text(x0 + w_code + 7, y + 1, label, size=size, fill=color, weight="bold", halo=False))


# ---------------------------------------------------------------- device icons
def dev_access(x, y, code, s=26):
    add(rect(x - s / 2, y - s / 2, s, s, fill=C_ACC, stroke="#cfe3ff", sw=1.5, rx=5))
    add(text(x, y + 4.5, code, size=12, fill="#fff", anchor="middle", weight="bold", halo=False))


def dev_sensor(x, y, code, r=14):
    add(circle(x, y, r, fill=C_SEN, stroke="#fff3c4", sw=1.5))
    add(text(x, y + 4.5, code, size=12, fill="#1a1300", anchor="middle", weight="bold",
             halo=False))


def dev_alarm(x, y, code, r=14):
    pts = [(x + r * 1.0 * c, y + r * 1.0 * s_) for c, s_ in
           [(-0.42, -1), (0.42, -1), (1, -0.42), (1, 0.42), (0.42, 1), (-0.42, 1), (-1, 0.42),
            (-1, -0.42)]]
    add(poly(pts, fill=C_ALM, stroke="#ffd6db", sw=1.5))
    add(text(x, y + 4.5, code, size=12, fill="#fff", anchor="middle", weight="bold", halo=False))


def smoke(x, y, r=12, color=C_SEN):
    add(poly([(x, y - r), (x + r, y), (x, y + r), (x - r, y)], fill=color, stroke="#fff3c4",
             sw=1.5))


def cctv(x, y, label, direction=1, lab_dx=0, lab_dy=-16, anchor="middle"):
    """Camera body + view cone (direction: angle in degrees of the cone)."""
    import math
    a = math.radians(direction)
    L = 70
    p1 = (x + L * math.cos(a - 0.45), y + L * math.sin(a - 0.45))
    p2 = (x + L * math.cos(a + 0.45), y + L * math.sin(a + 0.45))
    add(poly([(x, y), p1, p2], fill="#e6edf3", opacity=0.10))
    add(circle(x, y, 9, fill="#eceff1", stroke="#37474f", sw=2))
    add(circle(x, y, 3.5, fill="#263238"))
    add(text(x + lab_dx, y + lab_dy, label, size=12, anchor=anchor, weight="bold"))


def extinguisher(x, y):
    add(circle(x, y, 12, fill=C_EXT, stroke="#ffd0cb", sw=1.5))
    add(text(x, y + 4.5, "E", size=13, fill="#fff", anchor="middle", weight="bold", halo=False))


def th_sensor(x, y):
    add(circle(x, y, 10, fill="none", stroke=C_SEN, sw=2.5))
    add(circle(x, y, 4, fill=C_SEN))


# ================================================================ header
add(text(OX, 52, "Telecom Conecta — Plano de seguridad del centro de datos", size=30,
         weight="bold"))
add(text(OX, 84, "Proyecto Parcial 3 · Zona crítica: Servidor de clientes · Sala de 10 m × 8 m "
         "(redibujo y actualización del plano del Parcial 1)", size=15, fill=MUTED))
add(text(W - 40, 52, "Fecha: 2026-11-17", size=17, anchor="end", weight="bold"))
add(text(W - 40, 80, "Escala gráfica abajo · Norte de referencia: arriba", size=13, fill=MUTED,
         anchor="end"))

# ================================================================ grid (room + exterior)
gx0, gy0, gx1, gy1 = X(-0.6), Y(-0.5), X(15.0), Y(8.5)
g = []
k = 0
xm = -0.5
while X(xm) <= gx1:
    major = abs(xm - round(xm)) < 1e-6
    g.append(line(X(xm), gy0, X(xm), gy1, stroke="#1f2a36" if major else "#151d27",
                  sw=1.2 if major else 0.8))
    xm += 0.5
ym = -0.5
while Y(ym) <= gy1:
    major = abs(ym - round(ym)) < 1e-6
    g.append(line(gx0, Y(ym), gx1, Y(ym), stroke="#1f2a36" if major else "#151d27",
                  sw=1.2 if major else 0.8))
    ym += 0.5
add("".join(g))

# ================================================================ exterior zone (Z0)
add(rect(X(10.12), Y(-0.38), X(14.85) - X(10.12), Y(8.5) - Y(-0.38), stroke=Z_COL["Z0"],
         sw=2, dash="10 6", rx=10))
zone_tag(X(14.8), Y(-0.06), "Z0", "Exterior · perímetro", Z_COL["Z0"], anchor="end")

# ================================================================ room floor areas
# hot / cold aisles (centre band x 2.0–6.75)
ax0, ax1 = 2.0, 6.75
add(rect(X(ax0), Y(0.3), (ax1 - ax0) * S, 1.0 * S, fill=C_HOT, opacity=0.30))
add(rect(X(ax0), Y(2.3), (ax1 - ax0) * S, 1.2 * S, fill=C_COLD, opacity=0.35))
add(rect(X(ax0), Y(4.5), (ax1 - ax0) * S, 1.0 * S, fill=C_HOT, opacity=0.30))
add(text(X(2.1), Y(0.62), "Pasillo caliente (1,0 m)", size=13, fill="#ff9a8b", weight="bold"))
add(text(X(2.1), Y(2.58), "Pasillo frío (1,2 m)", size=13, fill="#5fe0d6", weight="bold"))
add(text(X(2.1), Y(4.82), "Pasillo caliente (1,0 m)", size=13, fill="#ff9a8b", weight="bold"))

# electric room, control room fills
add(rect(X(7.9), Y(4.8), 2.1 * S, 1.6 * S, fill=C_ELEC, opacity=0.16))
add(rect(X(7.0), Y(6.4), 3.0 * S, 1.6 * S, fill=C_CTRL, opacity=0.20))
# vestibule fill
add(rect(X(8.3), Y(2.4), 1.7 * S, 2.4 * S, fill="#4dd0e1", opacity=0.07))

# ================================================================ racks
client = {3, 4}   # indices 3,4 -> racks A4, A5, B4, B5
for row, yc in (("A", 1.8), ("B", 4.0)):
    for i in range(8):
        cx = 2.3 + i * 0.6
        hl = i in client
        if hl:
            add(circle(X(cx), Y(yc), 30, fill=C_CLIENT, opacity=0.22))
        add(circle(X(cx), Y(yc), 24, fill="#3a1b3a" if hl else C_RACK,
                   stroke=C_CLIENT if hl else C_RACK_EDGE, sw=3 if hl else 2))
        add(text(X(cx), Y(yc) + 4.5, f"{row}{i + 1}", size=12, anchor="middle", weight="bold",
                 fill="#ffd9fb" if hl else FG, halo=False))
add(text(X(6.62), Y(1.30) + 0, "", size=1))
add(text(X(1.98), Y(1.84), "Fila A", size=12, fill=MUTED, anchor="end"))
add(text(X(1.98), Y(4.04), "Fila B", size=12, fill=MUTED, anchor="end"))

# client-server bracket across the cold aisle
add(rect(X(3.72), Y(1.42), X(5.08) - X(3.72), Y(4.38) - Y(1.42), stroke=C_CLIENT, sw=2.5,
         dash="8 5", rx=12))
add(rect(X(3.78), Y(2.62), X(5.02) - X(3.78), 0.58 * S, fill=BG, stroke=C_CLIENT, sw=1.5, rx=6,
         opacity=0.95))
add(lines(X(4.4), Y(2.84), ["SERVIDOR DE", "CLIENTES"], size=13, fill=C_CLIENT, anchor="middle",
          weight="bold", halo=False, lh=17))

# ================================================================ walls & partitions
WALL = 6
add(rect(X(0), Y(0), 10 * S, 8 * S, stroke=C_WALL, sw=WALL))
part = [
    # server hall | corridor (door gap 2.45–3.35)
    (7.0, 0.0, 7.0, 2.45), (7.0, 3.35, 7.0, 8.0),
    # vestibule (turnstile gap 3.3–4.0)
    (8.3, 2.4, 10.0, 2.4), (8.3, 2.4, 8.3, 3.3), (8.3, 4.0, 8.3, 4.8),
    # electric room top + left wall (door gap 5.3–5.9)
    (7.9, 4.8, 10.0, 4.8), (7.9, 4.8, 7.9, 5.3), (7.9, 5.9, 7.9, 6.4),
    # control room top (door gap 7.15–7.75)
    (7.0, 6.4, 7.15, 6.4), (7.75, 6.4, 10.0, 6.4),
]
for x1, y1, x2, y2 in part:
    add(line(X(x1), Y(y1), X(x2), Y(y2), stroke=C_PART, sw=4, cap="square"))


def door(x1, y1, x2, y2, color, sw=7):
    add(line(X(x1), Y(y1), X(x2), Y(y2), stroke=BG, sw=WALL + 2))
    add(line(X(x1), Y(y1), X(x2), Y(y2), stroke=color, sw=sw))


# emergency exits (green)
door(0, 6.9, 0, 7.7, C_EXIT)
door(10, 0.45, 10, 1.25, C_EXIT)
# main entrance (access controlled, blue) + turnstile
door(10, 3.3, 10, 4.1, C_ACC)
add(circle(X(8.3), Y(3.65), 15, fill="none", stroke=C_ACC, sw=2.5))
for a in range(3):
    import math
    ang = math.radians(90 + a * 120)
    add(line(X(8.3), Y(3.65), X(8.3) + 15 * math.cos(ang), Y(3.65) + 15 * math.sin(ang),
             stroke=C_ACC, sw=2.5))
# server-room door (blue) with leaf + swing towards the corridor (egress direction)
add(line(X(7.0), Y(2.45), X(7.0), Y(3.35), stroke=C_ACC, sw=4, dash="4 4"))
add(line(X(7.0), Y(2.45), X(7.88), Y(2.45), stroke=C_ACC, sw=4))
add(path(f"M{X(7.88):.1f},{Y(2.45):.1f} A88,88 0 0 1 {X(7.0):.1f},{Y(3.35):.1f}",
         stroke=C_ACC, sw=1.5, dash="5 4", opacity=0.8))
# restricted doors (electric / control)
door(7.9, 5.3, 7.9, 5.9, C_ACC, sw=5)
door(7.15, 6.4, 7.75, 6.4, C_ACC, sw=5)

# ================================================================ left column (x 0–2)
add(rect(X(0.25), Y(0.3), 1.4 * S, 1.1 * S, fill=C_CRAC, opacity=0.85, stroke="#bcd7f5", sw=2,
         rx=6))
add(lines(X(0.95), Y(0.78), ["CRAC 1", "(CRAH)"], size=14, anchor="middle", weight="bold",
          halo=False, lh=18))
# flood sensor near CRAC
dev_sensor(X(0.45), Y(1.72), "S4")
add(text(X(0.68), Y(1.77), "Inundación", size=12, fill=C_SEN))
cctv(X(0.06), Y(2.25), "CCTV 2", direction=20, lab_dx=16, lab_dy=-12, anchor="start")
smoke(X(1.0), Y(2.95))
add(text(X(1.0), Y(3.32), "Detector de humo", size=11.5, fill=C_SEN, anchor="middle"))
add(lines(X(1.0), Y(4.1), ["Zona de", "circulación"], size=13, fill=MUTED, anchor="middle"))
# clean-agent suppression
add(rect(X(0.25), Y(5.35), 1.4 * S, 1.05 * S, fill="#1d2b22", stroke="#7bd88f", sw=2, rx=6))
for i, cx in enumerate((0.55, 0.95, 1.35)):
    add(rect(X(cx) - 12, Y(5.48), 24, 42, fill="#7bd88f", rx=10, opacity=0.9))
add(lines(X(0.95), Y(6.12), ["Supresión en sala", "FM-200 / Novec"], size=11.5, fill="#b9f0c4",
          anchor="middle", halo=False, lh=14))
# emergency exit label (outside left wall)
add(text(X(-0.3), Y(7.3), "SALIDA DE EMERGENCIA", size=13, fill=C_EXIT, weight="bold",
         anchor="middle", rotate=-90))

# ================================================================ centre column
# T/H sensor no.1 in hot aisle
th_sensor(X(4.75), Y(0.8))
dev_sensor(X(5.08), Y(0.8), "S5")
add(text(X(5.3), Y(0.85), "Sensor T/H n.º 1", size=12, fill=C_SEN))
# DHT11 in the cold aisle (replaces/accompanies T/H no.2)
dev_sensor(X(2.35), Y(3.05), "S1")
add(lines(X(2.55), Y(3.0), ["DHT11 (T/H n.º 2)", "temp./humedad"], size=12, fill=C_SEN, lh=15))
# HC-SR04 intrusion sensor inside the room, aimed at the cold aisle / door
add(path(f"M{X(6.1):.1f},{Y(2.9):.1f} L{X(5.35):.1f},{Y(2.55):.1f} "
         f"A80,80 0 0 0 {X(5.35):.1f},{Y(3.25):.1f} Z", fill=C_SEN, opacity=0.18))
dev_sensor(X(6.15), Y(2.9), "S2")
add(text(X(6.15), Y(2.62), "HC-SR04", size=12, fill=C_SEN, anchor="middle", weight="bold"))
add(text(X(6.15), Y(3.32), "intrusión", size=11.5, fill=C_SEN, anchor="middle"))
# exit button inside, next to the door
dev_access(X(6.72), Y(3.62), "A6")
add(text(X(6.53), Y(3.67), "Botón salida", size=11.5, fill="#9cc3ff", anchor="end"))

# smoke detectors (aspiration) under row B
for cx in (3.0, 4.4, 5.8):
    smoke(X(cx), Y(5.85))
    add(line(X(cx), Y(5.97), X(cx), Y(6.05), stroke=C_SEN, sw=2))
add(line(X(3.0), Y(6.05), X(5.8), Y(6.05), stroke=C_SEN, sw=2, dash="5 3"))
dev_sensor(X(6.3), Y(5.85), "S3")
add(text(X(4.4), Y(6.32), "Detección de humo: MQ-2 (demo) / VESDA por aspiración (real)",
         size=12, fill=C_SEN, anchor="middle"))
add(text(X(4.4), Y(6.82), "Zona de circulación", size=13, fill=MUTED, anchor="middle"))
extinguisher(X(2.5), Y(7.55))
add(text(X(2.72), Y(7.6), "Extintor 1 (CO₂/ABC)", size=12))

# ================================================================ right column
cctv(X(9.86), Y(0.12), "CCTV 1", direction=150, lab_dx=-16, lab_dy=26, anchor="end")
add(text(X(10.3), Y(0.92), "SALIDA", size=13, fill=C_EXIT, weight="bold"))
add(lines(X(8.85), Y(1.38), ["Corredor", "principal"], size=13, fill=MUTED, anchor="middle"))
extinguisher(X(9.7), Y(2.05))
add(text(X(9.48), Y(2.1), "Extintor 2", size=12, anchor="end"))

# server-room door devices (corridor side)
dev_access(X(7.55), Y(1.6), "A4")
add(lines(X(7.75), Y(1.56), ["Kiosco", "facial"], size=11.5, fill="#9cc3ff", lh=13))
dev_access(X(7.2), Y(2.12), "A7")
add(text(X(7.4), Y(2.17), "LCD 2004", size=11.5, fill="#9cc3ff"))
dev_access(X(7.22), Y(3.12), "A5")
add(text(X(7.42), Y(3.08), "Servo SG90", size=11.5, fill="#9cc3ff"))
add(text(X(7.42), Y(3.22), "(cerradura)", size=10.5, fill="#9cc3ff"))
dev_access(X(7.2), Y(3.62), "A3")
add(text(X(7.4), Y(3.67), "RFID RC522", size=11.5, fill="#9cc3ff"))
# ESP32 controller
add(rect(X(7.08), Y(3.88), 0.68 * S, 0.3 * S, fill="#263238", stroke=C_CTL, sw=2, rx=4))
add(text(X(7.42), Y(4.09), "ESP32", size=12, anchor="middle", weight="bold", fill="#eceff1",
         halo=False))
add(text(X(7.42), Y(4.32), "C1", size=10, anchor="middle", fill=C_CTL))
# alarm cluster
dev_alarm(X(7.2), Y(4.58), "R1")
dev_alarm(X(7.5), Y(4.58), "R2")
dev_alarm(X(7.8), Y(4.58), "R3")

# vestibule / reception (Z1)
add(rect(X(8.9), Y(4.15), 0.85 * S, 0.4 * S, fill="#16323a", stroke="#4dd0e1", sw=1.5, rx=4))
add(text(X(9.325), Y(4.41), "Recepción", size=12, anchor="middle", fill="#b2ebf2", halo=False))
dev_access(X(8.55), Y(3.05), "A1")
dev_access(X(8.88), Y(3.05), "A2")
add(circle(X(8.88) + 9, Y(3.05) - 9, 5, fill=C_EXIT, stroke="#fff", sw=1))
add(lines(X(8.45), Y(2.8), ["QR + LED verde"], size=11.5, fill="#9cc3ff"))
add(text(X(8.5), Y(3.8), "Torniquete", size=11, fill="#9cc3ff"))

# electric room (Z3)
add(text(X(8.95), Y(5.1), "Sala eléctrica", size=13, anchor="middle", weight="bold",
         fill="#ffc48a"))
for i, lab in enumerate(("UPS A", "UPS B")):
    x0 = 8.05 + i * 0.98
    add(rect(X(x0), Y(5.3), 0.85 * S, 0.8 * S, fill=C_UPS, opacity=0.85, stroke="#ffd2a6", sw=1.5,
             rx=5))
    add(text(X(x0 + 0.425), Y(5.75), lab, size=13, anchor="middle", weight="bold", halo=False))
dev_access(X(7.72), Y(5.12), "A8")

# control room (Z4)
add(text(X(8.68), Y(6.82), "Sala de control (3,0 × 1,6 m)", size=13, anchor="middle",
         weight="bold", fill="#dcc6ff"))
add(text(X(8.68), Y(7.05), "Monitoreo BMS / CCTV", size=12, anchor="middle", fill="#dcc6ff"))
add(rect(X(7.95), Y(7.25), 1.3 * S, 0.3 * S, fill="#3b2650", stroke="#c39bff", sw=1.5, rx=4))
add(text(X(8.6), Y(7.45), "Consola", size=11, anchor="middle", fill="#e8dbff", halo=False))
cctv(X(9.86), Y(7.86), "CCTV 3", direction=215, lab_dx=-18, lab_dy=-6, anchor="end")
dev_access(X(7.45), Y(6.18), "A8")

# ================================================================ exterior (right)
# main access approach
add(line(X(11.6), Y(3.7), X(10.12), Y(3.7), stroke=C_ACC, sw=3, marker="arrAcc"))
add(lines(X(10.3), Y(3.42), ["Acceso principal"], size=12.5, fill="#9cc3ff", weight="bold"))
add(lines(X(10.3), Y(4.25), ["Control de acceso", "(puerta + torniquete)"], size=12, fill="#9cc3ff",
          lh=15))
# utility feed + transformer
add(rect(X(11.45), Y(4.8), 2.8 * S, 0.6 * S, fill="#2a2015", stroke=C_UPS, sw=2, rx=6))
add(lines(X(12.85), Y(5.05), ["Acometida CFE + transformador", "(exterior)"], size=12.5,
          anchor="middle", fill="#ffd2a6", halo=False, lh=15))
# ATS A / B entering the electric room: solid = CFE utility, dashed = generators
UB, GB = 11.14, 11.3   # utility bus x, generator bus x
add(line(X(11.45), Y(5.1), X(UB), Y(5.1), stroke=C_UPS, sw=2.5))
add(line(X(UB), Y(5.1), X(UB), Y(6.04), stroke=C_UPS, sw=2.5))
for lab, yy in (("ATS A", 5.2), ("ATS B", 6.1)):
    add(rect(X(10.3), Y(yy) - 13, 0.7 * S, 26, fill="#3a2a17", stroke=C_UPS, sw=1.5, rx=4))
    add(text(X(10.65), Y(yy) + 4.5, lab, size=12, anchor="middle", weight="bold", halo=False,
             fill="#ffd2a6"))
    add(line(X(10.3), Y(yy), X(9.92), Y(yy), stroke=C_UPS, sw=2.5))
    add(line(X(11.0), Y(yy) - 6, X(UB), Y(yy) - 6, stroke=C_UPS, sw=2.5))
    add(line(X(11.0), Y(yy) + 6, X(GB), Y(yy) + 6, stroke="#ffcf9e", sw=2, dash="5 3"))
add(line(X(GB), Y(5.2) + 6, X(GB), Y(6.9), stroke="#ffcf9e", sw=2, dash="5 3"))
add(line(X(GB), Y(6.78), X(12.8), Y(6.78), stroke="#ffcf9e", sw=2, dash="5 3"))
add(line(X(12.8), Y(6.78), X(12.8), Y(6.9), stroke="#ffcf9e", sw=2, dash="5 3"))
# generator yard
add(rect(X(11.0), Y(6.45), 3.6 * S, 1.65 * S, stroke="#ffcf9e", sw=2, dash="8 5", rx=8))
add(text(X(12.95), Y(6.66), "EXTERIOR – Patio de generadores", size=13, anchor="middle",
         weight="bold", fill="#ffcf9e"))
for i, lab in enumerate(("GEN A (2N)", "GEN B (2N)")):
    x0 = 11.15 + i * 1.15
    add(rect(X(x0), Y(6.9), 1.0 * S, 0.65 * S, fill=C_UPS, opacity=0.85, stroke="#ffd2a6",
             sw=1.5, rx=5))
    add(text(X(x0 + 0.5), Y(7.28), lab, size=12, anchor="middle", weight="bold", halo=False))
add(rect(X(13.45), Y(6.9), 1.0 * S, 0.65 * S, fill="#5d4037", stroke="#bcaaa4", sw=1.5, rx=14))
add(lines(X(13.95), Y(7.18), ["Tanque", "diésel"], size=12, anchor="middle", halo=False,
          fill="#efebe9", lh=14))
add(text(X(12.8), Y(7.88), "Respaldo 2N: cada GEN alimenta su ATS/UPS", size=11, anchor="middle",
         fill="#ffcf9e"))

# ================================================================ evacuation routes
ev = dict(stroke=C_EXIT, sw=3, dash="10 6", marker="arrExit")
add(path(f"M{X(5.6):.1f},{Y(7.25):.1f} L{X(0.15):.1f},{Y(7.25):.1f}", **ev))
add(path(f"M{X(1.85):.1f},{Y(4.4):.1f} L{X(1.85):.1f},{Y(7.0):.1f}", **ev))
add(path(f"M{X(8.15):.1f},{Y(2.3):.1f} L{X(8.15):.1f},{Y(0.85):.1f} L{X(9.9):.1f},{Y(0.85):.1f}",
         **ev))
add(path(f"M{X(7.45):.1f},{Y(7.4):.1f} L{X(7.45):.1f},{Y(6.6):.1f}", **ev))
add(path(f"M{X(8.1):.1f},{Y(4.75):.1f} L{X(8.1):.1f},{Y(4.95):.1f}", stroke="none", sw=0))
add(path(f"M{X(9.6):.1f},{Y(3.9):.1f} L{X(9.92):.1f},{Y(3.9):.1f}", **ev))

# ================================================================ zone contours
def zone(x0, y0, x1, y1, col, sw=3, dash=None):
    add(rect(X(x0), Y(y0), X(x1) - X(x0), Y(y1) - Y(y0), stroke=col, sw=sw, dash=dash, rx=8))


zone(0.1, 0.1, 6.9, 7.9, Z_COL["Z2"], sw=3.5)
zone(8.38, 2.48, 9.92, 4.72, Z_COL["Z1"], sw=3, dash="9 5")
zone(7.98, 4.88, 9.92, 6.32, Z_COL["Z3"], sw=3)
zone(7.08, 6.48, 9.92, 7.92, Z_COL["Z4"], sw=3)
# zone tags
zone_tag(X(0), Y(-0.42), "Z2", "Sala de servidores — Servidor de clientes · Nivel 3 (zona crítica)",
         Z_COL["Z2"])
zone_tag(X(10.3), Y(2.6), "Z1", "Entrada principal / Recepción · Nivel 1", Z_COL["Z1"], size=12)
zone_tag(X(10.3), Y(5.0) - 30, "Z3", "Sala eléctrica · acceso restringido", Z_COL["Z3"], size=12)
zone_tag(X(10.3), Y(8.28), "Z4", "Sala de control · acceso restringido", Z_COL["Z4"], size=12)
add(line(X(10.3), Y(4.7) - 4, X(9.92), Y(4.92), stroke=Z_COL["Z3"], sw=1.5, dash="3 3"))
add(line(X(10.3), Y(8.28) - 4, X(9.92), Y(7.7), stroke=Z_COL["Z4"], sw=1.5, dash="3 3"))
add(line(X(10.3), Y(2.6) - 4, X(9.92), Y(2.6) - 4, stroke=Z_COL["Z1"], sw=1.5, dash="3 3"))

# ================================================================ always-exit note
nx, ny = X(0), Y(8.0) + 22
add(rect(nx, ny, 6.75 * S, 46, fill="#0f2a1a", stroke=C_EXIT, sw=2, rx=8))
add(text(nx + 14, ny + 20, "➜ Las personas siempre pueden salir (salidas de emergencia con barra antipánico).",
         size=14, fill="#a8f0c0", weight="bold", halo=False))
add(text(nx + 14, ny + 38, "Rutas de evacuación en verde; salidas de emergencia sin control de "
         "acceso (barra antipánico).", size=12, fill="#a8f0c0", halo=False))

# scale bar
sx, sy = X(7.05), Y(8.0) + 40
add(text(sx, sy - 10, "Escala gráfica (1 m = 100 px en el SVG)", size=12, fill=MUTED))
for i in range(3):
    add(rect(sx + i * S, sy, S, 10, fill=FG if i % 2 == 0 else BG, stroke=FG, sw=1))
    add(text(sx + i * S, sy + 26, f"{i} m", size=11, fill=MUTED, anchor="middle"))
add(text(sx + 3 * S, sy + 26, "3 m", size=11, fill=MUTED, anchor="middle"))

# ================================================================ device panel (right)
PX, PY, PW = X(15.25), Y(-0.55), W - X(15.25) - 30
entries = [
    ("Acceso", C_ACC, "acc", [
        ("A1", "Lector QR (webcam) — entrada principal"),
        ("A2", "LED verde = puerta abierta (5 s)"),
        ("A3", "Lector RFID RC522 — puerta Z2"),
        ("A4", "Kiosco de reconocimiento facial"),
        ("A5", "Cerradura servo SG90 (fail-closed)"),
        ("A6", "Botón de salida interior"),
        ("A7", "LCD 2004 I²C en la puerta"),
        ("A8", "Lector de acceso restringido (Z3/Z4)"),
    ]),
    ("Sensores", C_SEN, "sen", [
        ("S1", "DHT11 temp./humedad (pasillo frío)"),
        ("S2", "HC-SR04 ultrasónico de intrusión"),
        ("S3", "Humo: MQ-2 (demo) / VESDA (real)"),
        ("S4", "Sensor de inundación (CRAC)"),
        ("S5", "Sensor T/H n.º 1 (pasillo caliente)"),
    ]),
    ("Alarmas / actuadores", C_ALM, "alm", [
        ("R1", "Buzzer (alarma sonora)"),
        ("R2", "LED rojo (denegado / alarma)"),
        ("R3", "Ventilador: LED amarillo / relevador"),
    ]),
    ("Controlador", C_CTL, "ctl", [
        ("C1", "ESP32 (HTTP + HMAC con el backend)"),
    ]),
]
n_rows = sum(len(e[3]) for e in entries) + len(entries)
ph = 54 + n_rows * 27 + 10
add(rect(PX, PY, PW, ph, fill="#111823", stroke="#2c3a4a", sw=1.5, rx=10))
add(text(PX + 16, PY + 30, "Dispositivos del sistema", size=16, weight="bold", halo=False))
yy = PY + 62
for title, col, kind, items in entries:
    add(text(PX + 16, yy, title.upper(), size=12, fill=col, weight="bold", halo=False))
    yy += 27
    for code, desc in items:
        cx, cy = PX + 32, yy - 5
        if kind == "acc":
            dev_access(cx, cy, code, s=24)
        elif kind == "sen":
            dev_sensor(cx, cy, code, r=13)
        elif kind == "alm":
            dev_alarm(cx, cy, code, r=13)
        else:
            add(rect(cx - 14, cy - 11, 28, 22, fill="#263238", stroke=C_CTL, sw=1.5, rx=4))
            add(text(cx, cy + 4, code, size=11, anchor="middle", weight="bold", fill="#eceff1",
                     halo=False))
        add(text(cx + 24, yy, desc, size=12.5, halo=False))
        yy += 27

# access levels box under the panel
ly = PY + ph + 18
levels = [
    ("Z1", "Nivel 1", "QR válido + Registro 2 vigente"),
    ("Z2", "Nivel 3", "RFID + rostro + Registro 2 vigente"),
    ("Z3", "Restringido", "Solo personal eléctrico autorizado"),
    ("Z4", "Restringido", "Solo operadores de monitoreo"),
    ("Z0", "Exterior", "Perímetro, acometida y generadores"),
]
lh = 40 + len(levels) * 40 + 56
add(rect(PX, ly, PW, lh, fill="#111823", stroke="#2c3a4a", sw=1.5, rx=10))
add(text(PX + 16, ly + 30, "Niveles de acceso por zona", size=16, weight="bold", halo=False))
y2 = ly + 62
for code, lvl, desc in levels:
    col = Z_COL[code]
    add(rect(PX + 16, y2 - 15, 36, 22, fill=col, rx=11))
    add(text(PX + 34, y2 + 1, code, size=12, anchor="middle", weight="bold", fill=BG, halo=False))
    add(text(PX + 62, y2 + 1, lvl, size=12.5, weight="bold", fill=col, halo=False))
    add(text(PX + 62, y2 + 18, desc, size=11.5, fill=MUTED, halo=False))
    y2 += 40
add(text(PX + 16, y2 + 6, "Registro 1 (alta de ingenieros y rostros)", size=11.5, fill=FG,
         halo=False))
add(text(PX + 16, y2 + 22, "nunca concede acceso: solo el Registro 2.", size=11.5, fill=FG,
         halo=False))

# ================================================================ legend (bottom)
LX, LY = OX, Y(8.0) + 150
LW = W - LX - 30
add(rect(LX - 10, LY - 30, LW + 10, H - LY + 10, fill="#111823", stroke="#2c3a4a", sw=1.5, rx=10))
add(text(LX + 6, LY, "Leyenda", size=17, weight="bold", halo=False))

col_w = LW / 4
cells = []


def leg(draw, label):
    cells.append((draw, label))


def L_rect(fill, op=1, stroke="none", dash=None, sw=2):
    return lambda x, y: add(rect(x, y - 10, 40, 20, fill=fill, opacity=op, stroke=stroke, sw=sw,
                                 dash=dash, rx=3))


leg(L_rect(C_HOT, 0.45), "Pasillo caliente (1,0 m)")
leg(L_rect(C_COLD, 0.5), "Pasillo frío (1,2 m)")
leg(lambda x, y: (add(circle(x + 10, y, 9, fill=C_RACK, stroke=C_RACK_EDGE, sw=2)),
                  add(circle(x + 30, y, 9, fill=C_RACK, stroke=C_RACK_EDGE, sw=2))),
    "Estantes / racks (16)")
leg(lambda x, y: add(circle(x + 20, y, 10, fill="#3a1b3a", stroke=C_CLIENT, sw=3)),
    "Rack con Servidor de clientes")
leg(L_rect(C_CRAC, 0.85), "CRAC / CRAH (clima)")
leg(L_rect(C_UPS, 0.85), "UPS / generador 2N")
leg(L_rect(C_CTRL, 0.5), "Sala de control")
leg(lambda x, y: add(line(x, y, x + 40, y, stroke=C_EXIT, sw=7)), "Salida de emergencia")
leg(lambda x, y: add(line(x, y, x + 38, y, stroke=C_EXIT, sw=3, dash="10 6", marker="arrExit")),
    "Ruta de evacuación")
leg(lambda x, y: th_sensor(x + 20, y), "Sensor T/H")
leg(lambda x, y: cctv(x + 12, y, "", direction=0, lab_dy=0), "Cámara CCTV")
leg(lambda x, y: add(line(x, y, x + 40, y, stroke=C_ACC, sw=7)), "Puerta con control de acceso")
leg(lambda x, y: extinguisher(x + 20, y), "Extintor (CO₂/ABC)")
leg(lambda x, y: (add(rect(x + 6, y - 11, 28, 22, fill="#1d2b22", stroke="#7bd88f", sw=2, rx=4)),
                  add(rect(x + 15, y - 8, 10, 16, fill="#7bd88f", rx=4))),
    "Supresión gas limpio FM-200/Novec")
leg(lambda x, y: smoke(x + 20, y, r=11), "Detector de humo")
leg(lambda x, y: dev_access(x + 20, y, "A"), "Dispositivo de acceso (azul)")
leg(lambda x, y: dev_sensor(x + 20, y, "S"), "Sensor (ámbar)")
leg(lambda x, y: dev_alarm(x + 20, y, "R"), "Alarma / actuador (rojo)")
leg(lambda x, y: (add(rect(x + 2, y - 11, 36, 22, fill="#263238", stroke=C_CTL, sw=1.5, rx=4)),
                  add(text(x + 20, y + 4, "C", size=11, anchor="middle", weight="bold",
                           fill="#eceff1", halo=False))),
    "Controlador ESP32")
leg(lambda x, y: (add(circle(x + 20, y, 15, stroke=C_ACC, sw=2.5)),
                  add(line(x + 20, y, x + 20, y + 15, stroke=C_ACC, sw=2.5))),
    "Torniquete")
for zc, zl, dash in (("Z1", "Zona Z1 · Entrada / Recepción", "9 5"),
                     ("Z2", "Zona Z2 · Sala de servidores (crítica)", None),
                     ("Z3", "Zona Z3 · Sala eléctrica", None),
                     ("Z4", "Zona Z4 · Sala de control", None),
                     ("Z0", "Zona exterior (perímetro)", "10 6")):
    leg(L_rect("none", 1, Z_COL[zc], dash, sw=3), zl)

rows_per_col = (len(cells) + 3) // 4
for i, (draw, label) in enumerate(cells):
    c, r = divmod(i, rows_per_col)
    x = LX + 6 + c * col_w
    y = LY + 34 + r * 33
    draw(x, y)
    add(text(x + 54, y + 4.5, label, size=13, halo=False))

defs = arrow_marker("arrExit", C_EXIT, 12) + arrow_marker("arrAcc", C_ACC, 12)
H_final = int(LY + 34 + rows_per_col * 33 + 10)
# fix legend box height to its content
body = "\n".join(out).replace(
    f'height="{H - LY + 10:.1f}"', f'height="{H_final - LY + 20:.1f}"')
write_svg("plano_telecom_conecta", W, H_final + 30, body, defs, scale=1.6)
