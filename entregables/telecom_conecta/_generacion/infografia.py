import sys, asyncio
from playwright.async_api import async_playwright
OUT = sys.argv[1]
HTML = """<!doctype html><html lang=es><meta charset=utf-8><style>
*{box-sizing:border-box;margin:0}body{font-family:Arial,Helvetica,sans-serif;background:#fff}
#c{width:1240px;padding:56px 64px;background:linear-gradient(180deg,#0b1f3a 0,#0b1f3a 300px,#f4f7fb 300px);color:#14213d}
.brand{color:#7dd3fc;font-weight:700;letter-spacing:2px;font-size:20px}
h1{color:#fff;font-size:52px;line-height:1.1;margin:10px 0 12px}
.sub{color:#cbd5e1;font-size:22px;max-width:980px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:26px;margin-top:56px}
.card{background:#fff;border-radius:18px;padding:28px 30px;box-shadow:0 6px 20px rgba(15,23,42,.10)}
.card h2{font-size:25px;margin-bottom:14px;color:#0b1f3a;display:flex;gap:12px;align-items:center}
.n{background:#0ea5e9;color:#fff;border-radius:50%;width:38px;height:38px;display:inline-flex;align-items:center;justify-content:center;font-size:20px;flex:none}
p,li{font-size:19px;line-height:1.45;color:#334155}ul{padding-left:22px}li{margin:6px 0}
.flow{display:flex;gap:10px;margin-top:26px;align-items:stretch}
.step{flex:1;background:#0b1f3a;color:#fff;border-radius:14px;padding:18px 14px;text-align:center;font-size:18px;line-height:1.3}
.step b{display:block;color:#7dd3fc;font-size:30px;margin-bottom:6px}
.arrow{align-self:center;color:#0ea5e9;font-size:34px;font-weight:700}
.wide{grid-column:1/3}
.warn{border-left:8px solid #f59e0b}.ok{border-left:8px solid #10b981}
.foot{margin-top:28px;font-size:15px;color:#64748b;display:flex;justify-content:space-between}
</style><div id=c>
<div class=brand>TELECOM CONECTA · CENTRO DE DATOS · 17/11/2026</div>
<h1>Biometría con IA:<br>el rostro como segundo factor</h1>
<div class=sub>Tendencia: las redes neuronales profundas convierten un rostro en un vector numérico y lo comparan en milisegundos. Así lo aplicamos a la sala del Servidor de clientes.</div>
<div class=flow>
<div class=step><b>1</b>Tarjeta RFID<br>(algo que tienes)</div><div class=arrow>→</div>
<div class=step><b>2</b>Webcam captura<br>5 cuadros</div><div class=arrow>→</div>
<div class=step><b>3</b>IA (InsightFace)<br>vector de 512 números</div><div class=arrow>→</div>
<div class=step><b>4</b>Similitud ≥ 0.45<br>en ≥ 3 de 5 cuadros</div><div class=arrow>→</div>
<div class=step><b>5</b>Servo abre +<br>bitácora firmada</div>
</div>
<div class=grid>
<div class="card ok"><h2><span class=n>✓</span>Beneficios para Telecom Conecta</h2><ul>
<li>Una tarjeta prestada o clonada <b>no basta</b>: hace falta el rostro de su dueño.</li>
<li>No hay contraseñas que olvidar ni que compartir.</li>
<li>Cada intento queda en la bitácora con quién, cuándo, zona y resultado.</li>
<li>Funciona en local (edge): el rostro <b>no sale</b> del centro de datos.</li></ul></div>
<div class="card warn"><h2><span class=n>!</span>Riesgos y cómo los mitigamos</h2><ul>
<li><b>Suplantación con foto:</b> prueba de vida básica y varios cuadros.</li>
<li><b>Falsos rechazos:</b> umbral calibrado y registro con varias fotos.</li>
<li><b>Privacidad:</b> el biométrico es un dato sensible. Solo guardamos vectores cifrados y hay borrado a solicitud.</li>
<li><b>Sesgo del modelo:</b> hay que probar con personas diversas antes de usarlo en producción.</li></ul></div>
<div class=card><h2><span class=n>2</span>Biometría + menor privilegio</h2><p>El rostro <b>nunca concede acceso por sí solo</b>. El sistema exige además una solicitud aprobada y vigente (Registro 2) con su ventana de horario. Así, el personal de limpieza o un proveedor no entran a la sala aunque su rostro esté registrado.</p></div>
<div class=card><h2><span class=n>→</span>Hacia dónde va</h2><ul>
<li>Detección de vida con IR o profundidad (cámaras 3D).</li>
<li>Biometría multimodal: rostro y huella o voz.</li>
<li>Procesamiento en el borde (edge AI) junto a la puerta.</li>
<li>Normas de privacidad más estrictas para los datos biométricos.</li></ul></div>
<div class="card wide"><h2><span class=n>i</span>En un centro de datos real</h2><p>Para producción se usarían cámaras con detección de vida certificada (ISO/IEC 30107-3) y una esclusa (mantrap) que impida el <i>tailgating</i>. La biometría se integraría con el BMS y con el CCTV. En la maqueta usamos una webcam con InsightFace y un ESP32 con cerradura servo.</p></div>
</div>
<div class=foot><span>Proyecto Parcial 3 · Centros de Datos · Unidad III</span><span>Sistema DC Guardian · Telecom Conecta</span></div>
</div></html>"""
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(); pg = await b.new_page(device_scale_factor=2)
        await pg.set_content(HTML); await pg.locator("#c").screenshot(path=OUT); await b.close()
asyncio.run(main())
