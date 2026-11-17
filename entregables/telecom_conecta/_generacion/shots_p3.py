import sys, json, asyncio
from playwright.async_api import async_playwright
B = "http://127.0.0.1:8765"; pw = open(sys.argv[1]).read().strip(); OUT = sys.argv[2]; qr = json.load(open(sys.argv[3]))["qr_demo"]["eng2"]
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])
        ctx = await b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1.5, locale="es-MX",
                                  timezone_id="America/Mexico_City", color_scheme="light")
        pg = await ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
        r = await pg.request.post(B + "/api/v1/auth/login", data={"username": "admin", "password": pw}); print("login", r.status)
        async def shot(name, url, wait=2500, full=False):
            await pg.goto(B + url); await pg.wait_for_timeout(wait)
            await pg.screenshot(path=f"{OUT}/{name}.png", full_page=full); print(name)
        await shot("dashboard_dht11", "/pages/dashboard.html", 3500)
        await pg.locator(".card", has_text="Sala de servidores — DHT11").first.screenshot(path=f"{OUT}/dht11_panel.png"); print("dht11_panel")
        await shot("bitacora", "/pages/access-log.html", 2500)
        await shot("alertas", "/pages/alerts.html", 2500)
        await shot("simulador", "/pages/simulator.html", 3000)
        # Entrance: manual QR entry
        await pg.goto(B + "/pages/entrance.html"); await pg.wait_for_timeout(2500)
        await pg.fill("#manual-text", qr); await pg.press("#manual-text", "Enter"); await pg.wait_for_timeout(1500)
        await pg.screenshot(path=f"{OUT}/entrada_qr.png"); print("entrada_qr", await pg.inner_text("#result-title"))
        await pg.request.post(B + "/api/v1/sim/DC-DOOR-01/entrance-poll")
        # QR credential (issues a new QR for engineer 4: Proveedor)
        await pg.goto(B + "/pages/engineer.html?id=4"); await pg.wait_for_timeout(2500)
        pg.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
        await pg.click("#qr-issue"); await pg.wait_for_timeout(2500)
        await pg.locator("#qr-dlg").screenshot(path=f"{OUT}/credencial_qr.png"); print("credencial_qr")
        print("errors:", errs); await b.close()
asyncio.run(main())
