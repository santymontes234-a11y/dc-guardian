// Shell común: cabecera, navegación y sesión. Contrato estable (docs/api.md § Frontend):
//
//   <body data-page="requests">            ← clave del menú activo (ver NAV)
//     <main id="content"> … </main>
//     <script type="module" src="/js/pages/requests.js"></script>
//
//   // js/pages/requests.js
//   import { ready } from "/js/layout.js";
//   const admin = await ready;            // AdminOut de /auth/me (redirige al login si no hay sesión)
//   if (admin.role === "admin") { … }      // "admin" | "auditor"
//
// layout.js se importa desde la página; no hace falta un <script> aparte. Añadir una página
// al menú = añadir una entrada a NAV (solo integración edita esta lista).

import { api, escapeHtml, guarded } from "/js/api.js";
import { COMPANY, PRODUCT, startClock } from "/js/brand.js";

export const NAV = [
  { key: "dashboard", label: "Panel", href: "/pages/dashboard.html" },
  { key: "engineers", label: "Ingenieros", href: "/pages/engineers.html" },
  { key: "cards", label: "Tarjetas", href: "/pages/cards.html" },
  { key: "requests", label: "Solicitudes", href: "/pages/requests.html" },
  { key: "access", label: "Accesos", href: "/pages/access-log.html" },
  { key: "alerts", label: "Alertas", href: "/pages/alerts.html" },
  { key: "audit", label: "Auditoría", href: "/pages/audit.html" },
  { key: "entrance", label: "Entrada QR", href: "/pages/entrance.html", target: "_blank" },
  { key: "kiosk", label: "Kiosco", href: "/pages/kiosk.html", target: "_blank" },
];

function ensureStyles() {
  for (const href of ["/css/tokens.css", "/css/layout.css", "/css/components.css"]) {
    if (!document.querySelector(`link[href="${href}"]`)) {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = href;
      document.head.prepend(link);
    }
  }
}

function render(admin) {
  const current = document.body.dataset.page;
  const links = NAV
    .map((n) => `<a href="${n.href}" class="nav-link${n.key === current ? " active" : ""}"${
      n.target ? ` target="${n.target}" rel="noopener"` : ""}>${n.label}</a>`)
    .join("");

  const header = document.createElement("header");
  header.className = "app-header";
  header.innerHTML = `
    <a class="brand" href="/pages/dashboard.html"><span class="brand-company">${COMPANY}</span>
      <span class="brand-product">${PRODUCT}</span></a>
    <nav class="app-nav">${links}</nav>
    <div class="session">
      <time class="clock" id="header-clock"></time>
      <span class="who">${escapeHtml(admin.full_name)} · ${escapeHtml(admin.role)}</span>
      <button type="button" class="btn btn-ghost" id="logout">Salir</button>
    </div>`;
  document.body.prepend(header);
  startClock(header.querySelector("#header-clock"));
  document.body.classList.add(`role-${admin.role}`);

  header.querySelector("#logout").addEventListener("click", () =>
    guarded(async () => {
      await api.post("/auth/logout");
      window.location.href = "/index.html";
    }));
}

async function boot() {
  ensureStyles();
  const admin = await api.get("/auth/me");
  render(admin);
  return admin;
}

/** Promesa con el administrador actual; las páginas hacen `await ready` antes de cargar datos. */
export const ready = boot();
