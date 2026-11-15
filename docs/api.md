# API de DC Guardian (`/api/v1`)

> Referencia de integración. La especificación interactiva completa está en `http://localhost:8000/docs`
> (OpenAPI, desactivada en `prod`). El protocolo del ESP32 está en [protocolo-esp32.md](protocolo-esp32.md).

## URL base y despliegue

| Ejecución | URL base | Notas |
|---|---|---|
| Local (`uvicorn`) | `http://localhost:8000/api/v1` | `--host 0.0.0.0` para que llegue el ESP32 de la LAN |
| Docker (`docker compose up`) | `http://localhost:${DCG_PORT:-8000}/api/v1` | Un solo contenedor sirve la API, `/ws/events` y el frontend en el mismo origen |

Los cuerpos de `/device/*` están limitados a 4 KiB (`413 PAYLOAD_TOO_LARGE`). `GET /health` no requiere autenticación: `{"status": "ok", "simulation": bool}`. Lo usa el
healthcheck de Docker. Detrás de un proxy HTTPS, este debe reenviar `Upgrade`/`Connection` para el
WebSocket y el backend debe correr con `DCG_COOKIE_SECURE=true`.

## Convenciones

- **Autenticación de administradores:** cookie HttpOnly `dcg_session` (JWT) tras `POST /auth/login`. Roles:
  `admin` (lectura y escritura) y `auditor` (solo lectura).
- **Dispositivos:** HMAC por petición, sin JWT (ver protocolo).
- **Kiosco:** cabecera `X-Kiosk-Token` o una sesión `admin`.
- **Errores:** siempre `{"error": {"code", "message", "correlation_id", ...}}`. Cada respuesta lleva `X-Correlation-Id`.
- **Fechas:** ISO 8601 en UTC con zona horaria. **Estados persistidos:** en español y mayúsculas.
- **Paginación:** `?limit=` (1–200, por defecto 50) y `?offset=`. La respuesta tiene la forma `{items, total, limit, offset}`.

## Registro 1 — ingenieros (no conceden acceso)

| Método | Ruta | Descripción |
|---|---|---|
| GET · POST | `/engineers` | Listar (`status`, `q`) · crear. El `engineer_id` (`ENG-NNNN`) lo genera el sistema |
| GET | `/engineers/next-id` · `/engineers/stats` · `/engineers/by-code/{ENG-NNNN}` | Próximo ID, recuento por estado, búsqueda por código |
| GET · PATCH | `/engineers/{pk}` | Detalle · editar |
| POST | `/engineers/{pk}/status` | `{status, reason}`. Suspender o desactivar revoca las aprobadas y rechaza las pendientes |
| POST | `/engineers/{pk}/erase` | Borrado de datos personales y biométricos (estado `ELIMINADO`) |
| GET · POST · DELETE | `/engineers/{pk}/face` | Perfil biométrico · registrar muestras (multipart `images`, 3–5) · borrar todas |
| DELETE | `/engineers/{pk}/face/{sample_id}` | Borrar una muestra |
| POST | `/vision/quality` | Multipart `image`: indica si hay un único rostro, nitidez, iluminación y tamaño |

## Tarjetas, áreas y dispositivos

| Método | Ruta | Descripción |
|---|---|---|
| GET · POST | `/cards` | Listar (`status`, `engineer_id`, `unassigned`, `q`) · registrar `{uid, label?, engineer_id?}` |
| POST | `/cards/{id}/assign` · `/status` · `/unlock` | Vincular o desvincular · `ACTIVA/BLOQUEADA/PERDIDA/BAJA` · quitar el bloqueo por intentos fallidos |
| GET · POST · PATCH · DELETE | `/areas`, `/areas/{id}` | Catálogo de áreas |
| GET · POST · PATCH | `/devices`, `/devices/{id}` | `POST` devuelve el **secreto HMAC una sola vez** |
| POST | `/devices/{id}/rotate-secret` | Nuevo secreto (el anterior deja de valer al instante) |
| GET | `/devices/status/all` | Estado del hardware: `status`, último latido, puerta, distancia, sensores RC522 y HC-SR04, RSSI |
| POST | `/devices/{id}/emergency-close` | Encola `EMERGENCY_CLOSE` para el siguiente latido. **No existe orden remota de apertura** |

## Registro 2 — solicitudes de autorización (lo único que concede acceso)

| Método | Ruta | Descripción |
|---|---|---|
| GET · POST | `/requests` | Listar (`status`, `q`, `in_force`, ...) · crear (`engineer_id` como pk o `ENG-NNNN`, `card_id` o `card_uid`, `area_id`, `reason`, `start_at`, `duration_minutes` o `end_at`, `observations`) |
| GET | `/requests/stats` | `{by_status, in_force, total}` |
| POST | `/requests/{id}/approve` · `/reject` · `/revoke` · `/finalize` | Transiciones de estado. `403 SELF_AUTHORIZATION` si el administrador es el propio ingeniero |

## Acceso, alertas y panel

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/access-sessions` | Intentos de acceso (`state`, `direction`, `device_id`, `engineer_id`, `reason_code`, `since`) |
| GET | `/access-sessions/{id}` | Detalle: estado, motivo en español, `face_score`, distancias, marcas de tiempo |
| GET | `/alerts` · POST `/alerts/{id}/ack` | Alertas (`unacknowledged`, `severity`, `type`) · marcar como atendida |
| GET | `/stats/dashboard` | Ingenieros (por estado y quién está dentro), solicitudes, accesos, salidas y denegaciones en 24 h, denegaciones por motivo, alertas abiertas, dispositivos, últimos intentos |
| GET | `/audit` · `/audit/verify` | Auditoría encadenada con HMAC · verificación de la cadena |
| GET | `/system/kiosk-token` | Token del kiosco (solo `admin`) |

### Kiosco facial

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/kiosk/pending?device_code=DC-DOOR-01` | Intento que espera rostro en esa puerta: `{session: {id, expires_at, engineer}}` o `null` |
| POST | `/vision/verify` | Multipart: `session_id` + **exactamente** `DCG_FACE_FRAMES` (5) imágenes `frames` distintas, tomadas con unos 200 ms de separación. Responde `{state, reason_code, reason, score, matches, frames, retry}` |

`retry=true` (rostro no detectado, varios rostros o número de capturas incorrecto) mantiene la sesión
en `AWAITING_FACE` para que el kiosco reintente. `FACE_MISMATCH` y `LIVENESS_FAILED` deniegan la sesión.

### Dispositivo (ESP32, HMAC)

`POST /device/heartbeat`, `POST /device/presence`, `POST /device/access/start`,
`GET /device/access/{sid}?distance_cm=`, `POST /device/access/{sid}/opened`, `POST /device/access/{sid}/closed`
y `POST /device/event`. Contrato completo y firma de las respuestas en [protocolo-esp32.md](protocolo-esp32.md).

### Simulación (solo con `DCG_SIMULATION=true`, rol `admin`)

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/sim/state` | Puertas virtuales y tarjetas registradas |
| POST | `/sim/{device}/distance` · `/sensors` · `/online` · `/heartbeat` | Mover a la persona, simular un fallo del HC-SR04, desconectar el ESP32, enviar un latido |
| POST | `/sim/{device}/card` · `/face` · `/poll` · `/close` | Pasar tarjeta, enviar rostro sintético (`match`, `other` o `stranger`), sondear la decisión, cerrar el servo |
| POST | `/sim/enroll-demo-faces` | Registra un rostro sintético a cada ingeniero activo sin rostro |

El ESP32 virtual envía **peticiones HTTP firmadas reales** al propio gateway (`DCG_SIM_BASE_URL`).

## Tiempo real — `WS /ws/events`

Autenticación: cookie de administrador o auditor (debe coincidir el `Origin`), o token de kiosco enviado en el **primer mensaje** `{"kiosk_token": "..."}`, nunca en la URL (el kiosco solo recibe `access.*`).
Formato: `{"type", "ts", "data"}`. Los eventos se publican **después del commit**.

| Evento | `data` |
|---|---|
| `access.awaiting_face` · `face_retry` · `face_ok` · `granted` · `opened` · `closed` · `denied` · `timeout` · `exit_requested` | Sesión de acceso (igual que `GET /access-sessions/{id}`) |
| `alert.created` · `alert.acknowledged` | Alerta |
| `device.status` · `device.presence` | Estado de hardware · cambio de presencia |
| `request.updated` | `{id, use_count}` al consumir una autorización |

## Códigos de denegación (`reason_code`)

| Código | Motivo | Alerta |
|---|---|---|
| `UNKNOWN_CARD` | UID no registrado | `UNKNOWN_CARD` WARN |
| `CARD_NOT_ACTIVE` · `CARD_LOCKED` | Tarjeta bloqueada, perdida o dada de baja · bloqueo temporal por fallos | `CARD_BLOCKED` WARN |
| `CARD_NOT_LINKED` | Tarjeta sin ingeniero | `CARD_NOT_LINKED` WARN |
| `ENGINEER_INACTIVE` | Ingeniero inactivo, suspendido o eliminado | `INACTIVE_ENGINEER` **CRITICAL** |
| `NO_VALID_AUTH` · `AUTH_EXPIRED` · `AUTH_REVOKED` · `AUTH_REJECTED` | Sin solicitud vigente para esa tarjeta y área | `NO_VALID_AUTH` WARN |
| `REQUEST_PENDING` · `AUTH_NOT_STARTED` | Solicitud aún no aprobada · ventana futura | `NO_VALID_AUTH` INFO |
| `NO_FACE_ENROLLED` | Sin rostro registrado | `NO_FACE_ENROLLED` WARN |
| `FACE_MISMATCH` · `LIVENESS_FAILED` | El rostro no coincide · capturas idénticas | `FACE_MISMATCH` WARN |
| `PRESENCE_LOST` | La persona se alejó antes de la decisión | `PRESENCE_LOST` INFO |
| `SENSOR_ERROR` | Distancia no válida (HC-SR04) | `SENSOR_FAULT` WARN |
| `DEVICE_DISABLED` | Puerta deshabilitada | `DEVICE_DISABLED` WARN |
| `TIMEOUT` | Sin rostro dentro de `DCG_ACCESS_SESSION_TIMEOUT_S` (30 s) | — |
| `SESSION_SUPERSEDED` | Otra tarjeta en la misma puerta cancela el intento anterior | — |

Otras alertas:
- `REPEATED_FAILURES` (CRITICAL): 3 fallos en 5 min con la misma tarjeta la bloquean 10 min.
- `DEVICE_AUTH_FAIL` (CRITICAL): firma, nonce o timestamp inválidos.
- `DEVICE_OFFLINE` (WARN): sin latido durante más de 45 s.
- `SENSOR_FAULT` (WARN).
- `DEVICE_EVENT`.
- `EMERGENCY_CLOSE`.

## Frontend (contrato del shell)

- `import { api, ApiError, fmtDate, escapeHtml, toast, guarded } from "/js/api.js"`:
  - `api.get(path, query)`, `api.post`, `api.patch`, `api.del`, `api.upload(path, formData)`.
  - Las rutas son relativas a `/api/v1`. Un 401 redirige al login.
- Página: `<body data-page="clave"><main id="content">…</main>`. En su JS: `import { ready } from "/js/layout.js"; const admin = await ready;`.
- `/js/ws.js` exporta `connectEvents({kioskToken})` con `.on("access.*", fn)`. `/js/ui.js` contiene las tablas y etiquetas comunes y `reasonText(code)`.
- La clase `.admin-only` oculta las acciones de escritura a los auditores.
