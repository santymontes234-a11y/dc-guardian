import sys, asyncio
from playwright.async_api import async_playwright
B="http://127.0.0.1:8765"; pw=open(sys.argv[1]).read().strip(); OUT=sys.argv[2]
PAGES=[("02-panel","/pages/dashboard.html"),("03-ingenieros","/pages/engineers.html"),("04-ficha-ingeniero","/pages/engineer.html?id=1"),
("05-solicitudes","/pages/requests.html"),("06-tarjetas","/pages/cards.html"),("07-simulador","/pages/simulator.html"),
("08-accesos","/pages/access-log.html"),("09-alertas","/pages/alerts.html"),("10-auditoria","/pages/audit.html"),("11-kiosco","/pages/kiosk.html?device=DC-DOOR-01")]
async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch()
        ctx=await b.new_context(viewport={"width":1440,"height":900},device_scale_factor=1.5,locale="es-ES",timezone_id="America/Bogota",color_scheme="light")
        pg=await ctx.new_page()
        errs=[]; pg.on("pageerror",lambda e: errs.append(str(e)))
        await pg.goto(B+"/"); await pg.wait_for_timeout(1200)
        await pg.screenshot(path=f"{OUT}/01-login.png")
        r=await pg.request.post(B+"/api/v1/auth/login",data={"username":"admin","password":pw}); print("login",r.status)
        for name,url in PAGES:
            await pg.goto(B+url); await pg.wait_for_timeout(2500)
            if name=="10-auditoria":
                btn=pg.get_by_role("button",name="Verificar",exact=False)
                if await btn.count(): await btn.first.click(); await pg.wait_for_timeout(1500)
            await pg.screenshot(path=f"{OUT}/{name}.png")
            print(name, await pg.title())
        print("errors:",errs)
        await b.close()
asyncio.run(main())
