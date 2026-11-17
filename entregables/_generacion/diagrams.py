import sys, asyncio
from playwright.async_api import async_playwright
OUT=sys.argv[1]; D=sys.argv[2]
CSS="""
*{box-sizing:border-box} body{margin:0;font-family:'DejaVu Sans',Arial,sans-serif;background:#fff;color:#0B1B33}
#c{padding:28px;display:inline-block;background:#fff}
h1{font-size:20px;margin:0 0 18px;color:#0B1B33}
.box{border-radius:10px;padding:12px 14px;font-size:13px;line-height:1.35;background:#EEF3FB;border:1.5px solid #1F5FBF}
.box b{display:block;font-size:14px;margin-bottom:4px}
.dark{background:#0B1B33;color:#fff;border-color:#0B1B33}
.cyan{background:#E6F6F8;border-color:#2BB3C0}
.green{background:#E8F4EC;border-color:#1D7A46}
.red{background:#FBECEB;border-color:#B3261E}
.amber{background:#FBF2E4;border-color:#A86200}
.grey{background:#F3F4F6;border-color:#9AA5B4}
small{color:#5B6573;font-size:11px}
.note{font-size:11px;color:#5B6573;margin-top:14px}
"""
def page(title,body,w): return f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body><div id='c' style='width:{w}px'><h1>{title}</h1>{body}</div></body></html>"
SVGDEF="<defs><marker id='a' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='7' markerHeight='7' orient='auto-start-reverse'><path d='M0,0L10,5L0,10z' fill='#33415C'/></marker></defs>"
def svg(w,h,inner): return f"<svg width='{w}' height='{h}' xmlns='http://www.w3.org/2000/svg' style='font-family:DejaVu Sans,Arial'>{SVGDEF}{inner}</svg>"
def node(x,y,w,h,title,sub="",fill="#EEF3FB",stroke="#1F5FBF",tc="#0B1B33",fs=14):
    s=f"<rect x='{x}' y='{y}' width='{w}' height='{h}' rx='10' fill='{fill}' stroke='{stroke}' stroke-width='1.6'/>"
    lines=sub.split("|") if sub else []
    ty=y+h/2-(len(lines)*8) + (5 if not lines else 0)
    s+=f"<text x='{x+w/2}' y='{ty}' text-anchor='middle' font-size='{fs}' font-weight='bold' fill='{tc}'>{title}</text>"
    for i,l in enumerate(lines): s+=f"<text x='{x+w/2}' y='{ty+18+i*15}' text-anchor='middle' font-size='11.5' fill='{tc if tc!='#0B1B33' else '#33415C'}'>{l}</text>"
    return s
def arrow(x1,y1,x2,y2,label="",dash=False,both=False,lx=None,ly=None,color="#33415C"):
    d=" stroke-dasharray='6 4'" if dash else ""
    s=f"<line x1='{x1}' y1='{y1}' x2='{x2}' y2='{y2}' stroke='{color}' stroke-width='1.6' marker-end='url(#a)'{' marker-start=\"url(#a)\"' if both else ''}{d}/>"
    if label:
        lx=lx if lx is not None else (x1+x2)/2; ly=ly if ly is not None else (y1+y2)/2-6
        for i,l in enumerate(label.split("|")):
            s+=f"<text x='{lx}' y='{ly+i*13}' text-anchor='middle' font-size='11' fill='#33415C' style='paint-order:stroke;stroke:#fff;stroke-width:4px'>{l}</text>"
    return s
B="#EEF3FB";BS="#1F5FBF";C="#E6F6F8";CS="#2BB3C0";G="#E8F4EC";GS="#1D7A46";R="#FBECEB";RS="#B3261E";A="#FBF2E4";AS="#A86200";N="#0B1B33"
diags={}
# 1 Architecture
s=""
s+=node(30,30,200,70,"Administrador / auditor","navegador · cookie JWT",B,BS)
s+=node(30,190,200,80,"Kiosco facial","navegador + webcam|getUserMedia · 5 JPEG",C,CS)
s+=node(30,360,200,90,"ESP32 DevKit","RC522 · HC-SR04 · SG90|LCD 2004 · botón · LEDs|FreeRTOS · C++17",A,AS)
s+=f"<rect x='330' y='20' width='520' height='450' rx='14' fill='#F7F9FC' stroke='#9AA5B4' stroke-dasharray='6 4'/><text x='345' y='44' font-size='12' fill='#5B6573'>PC / servidor · proceso único (nativo o Docker)</text>"
s+=node(360,60,210,60,"Frontend estático","HTML + CSS + JS (sin build)",B,BS)
s+=node(610,60,210,60,"WebSocket /ws/events","eventos en vivo → panel y kiosco",B,BS)
s+=node(360,160,460,70,"Backend FastAPI · /api/v1","routers → services → models · 72 rutas REST + 1 WebSocket",N,N,"#FFFFFF",15)
s+=node(360,270,140,80,"Motor de acceso","multifactor|fail-closed",G,GS)
s+=node(520,270,140,80,"Visión facial","InsightFace buffalo_l|onnxruntime CPU",C,CS)
s+=node(680,270,140,80,"Auditoría","cadena HMAC-SHA256|+ alertas",R,RS)
s+=node(360,380,220,70,"SQLite (WAL)","Registro 1 · Registro 2 · logs",B,BS)
s+=node(600,380,220,70,"Scheduler","expiraciones · OFFLINE · barrido",B,BS)
s+=arrow(230,65,360,90,"REST + cookie")
s+=arrow(230,230,360,205,"POST /vision/verify|X-Kiosk-Token",ly=192,lx=295)
s+=arrow(230,405,360,215,"HTTP firmado HMAC|nonce + timestamp",both=True,lx=195,ly=318)
s+=arrow(715,120,715,160,both=True)
s+=arrow(465,120,465,160)
s+=arrow(430,230,430,270);s+=arrow(590,230,590,270);s+=arrow(750,230,750,270)
s+=arrow(430,350,450,380);s+=arrow(710,450,580,425)
diags["d1_arquitectura_general"]=("Arquitectura general de DC Guardian",svg(880,490,s),920)
# 2 sequence
cols=[("Ingeniero",80),("ESP32 + LCD",250),("Backend FastAPI",450),("Kiosco (webcam)",650),("SQLite / auditoría",830)]
s=""
for n,x in cols:
    s+=node(x-75,10,150,40,n,"",B if n!="Backend FastAPI" else N,BS if n!="Backend FastAPI" else N,"#0B1B33" if n!="Backend FastAPI" else "#fff",13)
    s+=f"<line x1='{x}' y1='50' x2='{x}' y2='640' stroke='#C5CCD6' stroke-dasharray='4 4'/>"
steps=[(80,250,"1 · acerca la tarjeta RFID"),(250,450,"2 · POST /device/access/start {uid} (firmado)"),(450,830,"3 · tarjeta → ingeniero → solicitud APROBADA vigente"),(450,250,"4 · AWAITING_FACE + session_id (firmado)"),(250,250,"LCD: RECONOCIMIENTO FACIAL"),(450,650,"5 · evento access.awaiting_face (WS)"),(650,450,"6 · POST /vision/verify (5 fotogramas)"),(450,450,"7 · embedding 512-d · coseno ≥ 0,45 en ≥ 3/5 · liveness"),(250,450,"8 · GET /device/access/{sid} (sondeo 500 ms)"),(450,830,"9 · revalida Registro 2 justo antes de conceder"),(450,250,"10 · GRANTED {open_ms, greeting} (firmado)"),(250,250,"servo 90° · LCD: ACCESO AUTORIZADO"),(250,450,"11 · POST /opened … POST /closed"),(450,830,"12 · sesión + auditoría encadenada + alertas")]
y=80
for a,b,t in steps:
    if a==b:
        s+=f"<rect x='{a-8}' y='{y-14}' width='16' height='22' fill='#2BB3C0' rx='3'/><text x='{a+16}' y='{y+2}' font-size='11.5' fill='#0B1B33'>{t}</text>"
    else:
        s+=arrow(a,y,b,y,dash=(b<a and False))
        s+=f"<text x='{(a+b)/2}' y='{y-6}' text-anchor='middle' font-size='11.5' fill='#0B1B33' style='paint-order:stroke;stroke:#fff;stroke-width:4px'>{t}</text>"
    y+=40
diags["d2_secuencia_acceso"]=("Flujo de entrada: tarjeta → autorización → rostro → apertura firmada",svg(920,650,s),960)
# 3 state machine
s=""
st=[("CARD_READ",30,150,G,GS),("AWAITING_FACE",210,150,B,BS),("FACE_OK",390,150,B,BS),("GRANTED",570,150,G,GS),("OPENED",750,150,G,GS),("CLOSED",750,300,G,GS),("DENIED",300,330,R,RS),("TIMEOUT",210,20,A,AS)]
for n,x,y,f,c in st: s+=node(x,y,150,52,n,"",f,c)
s+=arrow(180,176,210,176,"checks OK",ly=146);s+=arrow(360,176,390,176,"1:1 OK",ly=146);s+=arrow(540,176,570,176,"revalida",ly=146);s+=arrow(720,176,750,176,"servo",ly=146)
s+=arrow(825,202,825,300,"cierre",lx=860,ly=255)
s+=arrow(285,150,285,72,"30 s sin rostro",dash=True,lx=345,ly=115)
s+=arrow(105,202,330,330,"tarjeta inválida|sin autorización",lx=150,ly=280)
s+=arrow(285,202,360,330,"rostro no|coincide",lx=280,ly=270)
s+=arrow(465,202,420,330,"revocada /|suspendido",lx=500,ly=270)
s+=f"<text x='30' y='420' font-size='11.5' fill='#5B6573'>Estados terminales: CLOSED, DENIED, TIMEOUT. El ESP32 solo actúa con GRANTED firmado y ligado a su propia sesión.</text>"
diags["d3_estados_sesion_acceso"]=("Máquina de estados de la sesión de acceso (backend)",svg(920,430,s),960)
# 4 request lifecycle
s=""
s+=node(30,140,150,52,"PENDIENTE","",A,AS)
s+=node(260,60,150,52,"APROBADA","",G,GS);s+=node(260,230,150,52,"RECHAZADA","",R,RS)
s+=node(500,10,150,52,"FINALIZADA","",B,BS);s+=node(500,100,150,52,"EXPIRADA","",B,BS);s+=node(500,190,150,52,"REVOCADA","",R,RS)
s+=arrow(180,155,260,90,"aprobar|(no a sí mismo)",lx=200,ly=105);s+=arrow(180,178,260,255,"rechazar",lx=200,ly=235)
s+=arrow(410,78,500,40,"finalizar",ly=50);s+=arrow(410,86,500,126,"vence la ventana|(scheduler)",lx=455,ly=95);s+=arrow(410,100,500,210,"revocar /|suspender ingeniero",lx=440,ly=170)
s+=f"<text x='30' y='310' font-size='11.5' fill='#5B6573'>Solo una solicitud APROBADA y dentro de su ventana horaria (Registro 2) permite abrir la puerta.</text>"
diags["d4_ciclo_solicitud"]=("Ciclo de vida de una solicitud de autorización (Registro 2)",svg(680,320,s),720)
# 5 HMAC protocol
s=""
s+=node(20,30,230,150,"ESP32","1. nonce aleatorio (RNG HW)|2. timestamp NTP|3. HMAC-SHA256(secreto,|método·ruta·query·ts·nonce·|SHA256(cuerpo))",A,AS)
s+=node(470,30,240,150,"Gateway /device/*","comprueba firma (tiempo constante)|reloj ±30 s · nonce único|cuerpo ≤ 4 KiB · query canónica|decide con el motor de acceso",N,N,"#fff")
s+=arrow(250,80,470,80,"petición + X-Device-Id|X-Timestamp · X-Nonce|X-Signature",ly=50)
s+=arrow(470,140,250,140,"respuesta firmada|ligada al nonce de la petición",ly=160)
s+=node(20,230,690,70,"Firma, nonce o reloj inválidos → 401 + alerta CRITICAL","El ESP32 descarta toda respuesta sin firma válida o de otra sesión: la puerta queda cerrada (fail-closed)",R,RS,fs=12.5)
diags["d5_protocolo_hmac"]=("Protocolo ESP32 ↔ backend (HTTP firmado)",svg(730,320,s),770)
# 6 face pipeline
s=""
items=[("Webcam","kiosco · navegador",C,CS),("5 fotogramas JPEG","en memoria, nunca a disco",B,BS),("Calidad","1 rostro · tamaño ≥ 80 px|nitidez · pose",B,BS),("InsightFace","buffalo_l · embedding|512 dimensiones",C,CS),("Coseno 1:1","vs plantilla del titular|≥ 0,45 en ≥ 3 de 5",B,BS),("Liveness básica","fotogramas no idénticos",A,AS),("Decisión","FACE_OK · reintento|o DENIED",G,GS)]
x=10
for i,(t,sub,f,c) in enumerate(items):
    s+=node(x,30,140,90,t,sub,f,c,fs=13)
    if i<len(items)-1: s+=arrow(x+140,75,x+160,75)
    x+=160
diags["d6_pipeline_facial"]=("Verificación facial 1:1 en el backend",svg(1130,140,s),1170)
# 7 hardware
s=""
s+=node(330,120,200,220,"ESP32 DevKit v1","ESP32-WROOM-32|WiFi 2,4 GHz|FreeRTOS|watchdog",N,N,"#fff")
hw=[("RC522 (RFID)","SPI: SS 5 · SCK 18|MOSI 23 · MISO 19 · RST 22|3,3 V",20,20,A,AS),("HC-SR04 (interior)","TRIG 26 · ECHO 27|divisor 1 kΩ / 2 kΩ · 5 V",20,170,C,CS),("Botón de salida","GPIO 4 · pull-up interno",20,320,B,BS),
("Servo SG90","señal GPIO 13 · PWM 50 Hz|0° cerrado · 90° abierto",640,20,G,GS),("LCD 2004 I2C","SDA 21 · SCL 17|PCF8574 0x27 / 0x3F",640,170,B,BS),("LEDs + zumbador","verde 25 · rojo 33|zumbador 32 (2N2222)",640,320,R,RS)]
for i,(t,sub,x,y,f,c) in enumerate(hw):
    s+=node(x,y,210,95,t,sub,f,c,fs=13)
    ey=160+(i%3)*70
    if x<300: s+=arrow(230,y+47,330,ey)
    else: s+=arrow(530,ey,640,y+47)
diags["d7_hardware_conexiones"]=("Hardware de la puerta y asignación de pines (pins.h)",svg(870,430,s),910)
async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch(); pg=await b.new_page(device_scale_factor=2)
        for name,(title,body,w) in diags.items():
            html=page(title,body,w); open(f"{D}/{name}.html","w").write(html)
            await pg.set_content(html); await pg.locator("#c").screenshot(path=f"{OUT}/{name}.png"); print(name)
        await b.close()
asyncio.run(main())
