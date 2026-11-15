# Auditoría final — DC Guardian (2026-11-14)

Revisión del estado del proyecto **antes** de la fase de cierre (LCD, Docker, documentación y
publicación). Todo lo indicado como "verificado" se ejecutó realmente durante la auditoría.

## 1. Resumen

| Área | Estado encontrado | Acción |
|---|---|---|
| Backend FastAPI | Completo: auth JWT/cookie, Registro 1 y 2, motor de acceso, gateway HMAC del ESP32, alertas, auditoría encadenada, WebSocket, scheduler, simulación | Conservar |
| Tests backend | **Verificado**: `pytest` termina con código 0 (198 pruebas) | Conservar |
| Base de datos | SQLite + Alembic (5 migraciones), tipos UTC | Conservar; persistir en volumen Docker |
| Reconocimiento facial | InsightFace `buffalo_l` en el backend; la webcam la abre el **navegador** (getUserMedia) y envía fotogramas | Conservar; condiciona el diseño Docker (ver §4) |
| Frontend | Solo 4 páginas (ingenieros, alta, ficha, solicitudes). El menú enlaza 8 páginas **inexistentes**: `index.html` (login), `dashboard`, `cards`, `access-log`, `alerts`, `audit`, `simulator`, `kiosk` | **Crear** las páginas que faltan |
| Servir el frontend | `app/main.py` solo monta `frontend/` si existe `frontend/index.html` → hoy la interfaz **no se sirve** | Se resuelve al crear `index.html` |
| Firmware ESP32 | Sólido: lógica pura en `lib/dcg_core` con pruebas Unity, tarea FreeRTOS de E/S, HMAC, watchdog, fail-closed | Conservar |
| LCD 2004 I2C | **No existe** (ni código, ni pines, ni librería, ni documentación) | **Implementar** módulo no bloqueante + máquina de estados |
| Docker | No existe | Crear Dockerfile, compose, `.dockerignore` |
| requirements.txt | No existe (dependencias en `pyproject.toml` + `uv.lock`) | Generar desde el lock |
| Documentación | `README.md` desactualizado (marca F4–F8 como pendientes, ya están hechas); faltan LICENSE, CONTRIBUTING, SECURITY, `docs/api.md` (citado por `api.js` y `layout.js`), `docs/installation.md`, `docs/hardware.md` | Crear / actualizar |
| Git | El directorio **no es** un repositorio git | Inicializar, rama `main` |

## 2. Errores y problemas de integración

1. **Interfaz inaccesible**: sin `frontend/index.html` FastAPI no monta los estáticos; la ruta `/`
   devuelve 404 y las páginas existentes no se pueden abrir desde el servidor.
2. **Enlaces rotos en el menú** (`layout.js → NAV`): 8 destinos sin página.
3. **Kiosco ausente**: el backend ya expone `/kiosk/pending`, `/vision/verify` y
   `/ws/events?kiosk_token=…`, pero no hay página que use la webcam en la puerta. Sin ella el
   reconocimiento facial solo funciona en modo simulación.
4. **Dependencias de visión**: `insightface 2.1` declara `opencv-python` (con GUI) además del
   `opencv-python-headless` del proyecto; ambos se instalan y comparten el módulo `cv2`. En un
   contenedor conviene una sola variante (headless) para no arrastrar librerías X11.
5. **README** contradice el estado real (fases marcadas como pendientes).

## 3. Seguridad y configuración

| Punto | Estado |
|---|---|
| `.gitignore` | Correcto para `data/`, `.env`, `dcg_config.h`, `.pio/`. Falta `.claude/settings.local.json` y artefactos varios |
| Secretos en el árbol | `data/.dev_keys.json` (claves dev) y `data/models/` (≈ 300 MB): ignorados por git. No hay `backend/.env` |
| Firmware | El secreto HMAC solo vive en `include/dcg_config.h` (ignorado). Placeholder rechazado en arranque |
| `prod` | El backend exige secretos, `COOKIE_SECURE=true` y prohíbe el proveedor facial *mock* |
| Docker (a crear) | Debe ejecutarse sin root y montar `data/` como volumen; nunca copiar `data/` a la imagen |
| Paquete `insightface_privateframe_bootstrap` | Revisado: CLI opcional de InsightFace, solo stdlib; no ejecuta nada al importar `insightface` |

## 4. Webcam y Docker (decisión de diseño)

La webcam **no** la usa Python: la abre el navegador del kiosco con `getUserMedia`, captura N
fotogramas JPEG y los envía por HTTP a `/vision/verify`, donde InsightFace calcula el
embedding. Por tanto:

- No hace falta pasar `/dev/video0` a ningún contenedor ni crear un servicio "face recognition"
  aparte: la inferencia ya ocurre en el backend.
- `getUserMedia` exige contexto seguro: funciona en `http://localhost` (mismo PC) o con HTTPS.
  Abrir el kiosco desde otra máquina por `http://IP` **no** funcionará sin TLS.

## 5. Servicios descartados

- **MQTT/Mosquitto**: descartado. El protocolo definitivo del ESP32 es HTTP con peticiones y
  respuestas firmadas con HMAC (`docs/protocolo-esp32.md`); un broker añadiría superficie sin
  aportar nada.
- **Contenedor de base de datos**: SQLite es un archivo; basta un volumen.
- **Nginx**: FastAPI ya sirve los estáticos y el WebSocket. Se deja como opción documentada
  para HTTPS (necesario si el kiosco se abre desde otro equipo).

## 6. Código duplicado / deuda menor

- `simulator/esp32_sim.py` y `firmware/esp32-door/tools/mock_gateway.py` son herramientas con
  propósitos distintos (ESP32 virtual contra el backend real vs. backend falso para el
  firmware). No se fusionan.
- `.pio/` contiene binarios de compilación: ignorado por git.
