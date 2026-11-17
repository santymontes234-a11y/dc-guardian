import { ready } from "/js/layout.js";
import { guarded } from "/js/api.js";
import { connectEvents } from "/js/ws.js";
import { $, emptyRow } from "/js/ui.js";
import { LOG_COLS, LOG_HEAD, fetchAccessLog, logRow } from "/js/access-log.js";

await ready;
$("head").innerHTML = LOG_HEAD;

const params = new URLSearchParams(location.search);
if (params.get("zone")) $("zone").value = params.get("zone");
let limit = 50;

async function load() {
  const page = await guarded(() => fetchAccessLog({
    zone: $("zone").value, result: $("result").value, method: $("method").value, limit,
  }));
  if (!page) return;
  $("legacy-note").hidden = !page.legacy;
  $("total").textContent = `${page.items.length} de ${page.total}`;
  $("rows").innerHTML = page.items.map(logRow).join("") || emptyRow(LOG_COLS, "Sin registros");
}

for (const id of ["zone", "result", "method"]) $(id).addEventListener("change", () => { limit = 50; load(); });
$("more").addEventListener("click", () => { limit = Math.min(limit + 50, 200); load(); });

let t;
connectEvents().on("*", (evt) => {
  if (!evt?.type || evt.type === "environment" || evt.type.startsWith("device.")) return;
  if (/^(access|entrance|qr)\./.test(evt.type) || evt.type === "access") {
    clearTimeout(t);
    t = setTimeout(load, 300);
  }
});
load();
