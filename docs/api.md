# API de DC Guardian (`/api/v1`)

> Referencia de integración. La especificación interactiva completa está en `http://localhost:8000/docs`
> (OpenAPI, desactivada en `prod`). El protocolo del ESP32 está en [protocolo-esp32.md](protocolo-esp32.md).

## URL base y despliegue

| Ejecución | URL base | Notas |
|---|---|---|
| Local (`uvicorn`) | `http://localhost:8000/api/v1` | `--host 0.0.0.0` para que llegue el ESP32 de la LAN |
| Docker (`docker compose up`) | `http://localhost:${DCG_PORT:-8000}/api/v1` | Un solo contenedor sirve la API, `/ws/events` y el frontend en el mismo origen |

Los cuerpos de `/device/*` están limitados a 4 KiB (`413 PAYLOAD_TOO_LARGE`). `GET /health` no requiere autenticación: `{"status": "ok"}`. Lo usa el
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
| POST | `/engineers/{pk}/qr` | Emite la credencial QR de la entrada principal (solo `admin`). Cuerpo opcional: sin cuerpo = permanente; `{valid_minutes}` (5 a 43200, contados desde ahora con el reloj del servidor) o `{expires_at}` (no ambos) = **pase temporal**; `{single_use: true}` = el primer acceso concedido lo consume (exige vencimiento: `422 QR_SINGLE_USE_NEEDS_EXPIRY`). `201 {qr_text, prefix, expires_at, single_use, engineer:{id, full_name, position}}`. El `qr_text` (`DCG-QR1:<token>`) se devuelve **una sola vez**; solo se guarda su SHA-256. Revoca el QR anterior. `409 ENGINEER_NOT_ACTIVE` si el ingeniero no está `ACTIVO` |
| GET | `/engineers/{pk}/qr` | `{active, expired, single_use, prefix, created_at, expires_at, last_used_at}`, nunca el token (solo `admin`). `expired` es `true` si sigue `ACTIVA` en la base pero ya pasó su vencimiento |
| DELETE | `/engineers/{pk}/qr` | `204`: revoca el QR activo · `404 QR_NOT_FOUND` si no hay ninguno. Borrar los datos del ingeniero también lo revoca |

El QR **identifica, no autoriza**: cada escaneo exige además una solicitud `APROBADA` vigente (Registro 2).

## Tarjetas, áreas y dispositivos

| Método | Ruta | Descripción |
|---|---|---|
| GET · POST | `/cards` | Listar (`status`, `engineer_id`, `unassigned`, `q`) · registrar `{uid, label?, engineer_id?}` |
| POST | `/cards/{id}/assign` · `/status` · `/unlock` | Vincular o desvincular · `ACTIVA/BLOQUEADA/PERDIDA/BAJA` · quitar el bloqueo por intentos fallidos |
| GET · POST · PATCH · DELETE | `/areas`, `/areas/{id}` | Catálogo de áreas (código: letras, dígitos, `-` y `_`, p. ej. `ENTRADA_PRINCIPAL`, `SALA_SERVIDORES`) |
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
| GET | `/access-log` | **Bitácora** de todas las zonas y métodos (ver abajo). Filtros `method`, `result`, `zone`, `engineer_id`, `since`, `until` |
| GET | `/access-sessions` | Intentos de acceso (`state`, `direction`, `device_id`, `engineer_id`, `reason_code`, `since`) |
| GET | `/access-sessions/{id}` | Detalle: estado, motivo en español, `face_score`, distancias, marcas de tiempo |
| GET | `/alerts` · POST `/alerts/{id}/ack` | Alertas (`unacknowledged`, `severity`, `type`) · marcar como atendida |
| GET | `/stats/dashboard` | Ingenieros (por estado y quién está dentro), solicitudes, accesos, salidas y denegaciones en 24 h, denegaciones por motivo, alertas abiertas, dispositivos, últimos intentos |
| GET | `/audit` · `/audit/verify` | Auditoría encadenada con HMAC · verificación de la cadena |
| GET | `/system/kiosk-token` | Token del kiosco (solo `admin`) |
| GET | `/system/notifications` | `{telegram:{configured, min_severity, site_name}}` (solo `admin`). Nunca devuelve el token ni el chat id |
| POST | `/system/notifications/test` | Envía un mensaje de prueba a Telegram (solo `admin`, auditado). `200 {sent: true}` · `409 NOTIFICATIONS_NOT_CONFIGURED` · `502 NOTIFY_FAILED` |
| GET | `/monitoring/environment/latest` | Última lectura del DHT11: `{device_code, area, temperature_c, humidity_pct, sensor, fan, alarm, conditions, at, thresholds:{temp_high_c, temp_critical_c, humidity_low_pct, humidity_high_pct, fan_off_below_c}}`. `?device_code=` opcional |
| GET | `/monitoring/environment?minutes=60` | `{minutes, items:[{at, temperature_c, humidity_pct}]}`, del más antiguo al más reciente. `minutes` 1–10080; como máximo 1440 puntos (se submuestrea) |

### Bitácora (`GET /access-log`)

Paginada (`{items, total, limit, offset}`), de la más reciente a la más antigua. Reúne los intentos **decididos**
de la sala (`access_sessions`; los que aún esperan rostro no aparecen) y los escaneos QR de la entrada principal
(`entrance_events`). Cada fila:

```json
{
  "id": "9f1c…(32 hex)",
  "source": "entrance_event",
  "at": "2026-11-17T14:02:11.120000+00:00",
  "person": "Laura Méndez Ríos",
  "engineer_id": "ENG-0001",
  "position": "Administrador de TI",
  "zone": {"code": "ENTRADA_PRINCIPAL", "name": "Entrada principal / recepción"},
  "method": "QR",
  "direction": "ENTRADA",
  "result": "GRANTED",
  "reason_code": null,
  "reason": null,
  "device_code": "DC-DOOR-01"
}
```

- `source`: `access_session` (tarjeta + rostro o botón de salida) o `entrance_event` (QR).
- `method`: `QR`, `RFID+ROSTRO` o `BOTON_SALIDA` (botón de salida interior, sin tarjeta ni rostro).
- `result`: `GRANTED` (concedido, abierto o cerrado) o `DENIED` (denegado o tiempo agotado), con `reason_code` y `reason`.
- `person`, `engineer_id` y `position` valen `null` si no se sabe quién era (QR desconocido, tarjeta no registrada).

### Kiosco facial

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/kiosk/pending?device_code=DC-DOOR-01` | Intento que espera rostro en esa puerta: `{session: {id, expires_at, engineer}}` o `null` |
| POST | `/vision/verify` | Multipart: `session_id` + **exactamente** `DCG_FACE_FRAMES` (5) imágenes `frames` distintas, tomadas con unos 200 ms de separación. Responde `{state, reason_code, reason, score, matches, frames, retry}` |

`retry=true` (rostro no detectado, varios rostros o número de capturas incorrecto) mantiene la sesión
en `AWAITING_FACE` para que el kiosco reintente. `FACE_MISMATCH` y `LIVENESS_FAILED` deniegan la sesión.

### Entrada principal: escaneo QR (kiosco de recepción)

`POST /kiosk/entrance/scan` con `{qr_text}` (máx. 512 caracteres). Misma autenticación que `/kiosk/*`
(`X-Kiosk-Token` o sesión `admin`; un auditor recibe `403`). Respuesta 200:

```json
{"result": "GRANTED", "display_name": "Laura Méndez Ríos", "position": "Administrador de TI",
 "area": "ENTRADA_PRINCIPAL", "event_id": "9f1c…"}
{"result": "DENIED", "reason_code": "NO_VALID_AUTH", "reason": "No existe ninguna autorización…",
 "area": "ENTRADA_PRINCIPAL", "event_id": "…"}
```

Comprobaciones en este orden (la primera que falla deniega): `QR_INVALID` (formato distinto de `DCG-QR1:<32 car.>`),
`QR_UNKNOWN`, `QR_REVOKED`, `QR_USED` (pase de un solo uso ya gastado), `QR_EXPIRED`, `ENGINEER_INACTIVE`, Registro 2 (los mismos códigos que la puerta:
`NO_VALID_AUTH`, `REQUEST_PENDING`, `AUTH_NOT_STARTED`, `AUTH_EXPIRED`, `AUTH_REVOKED`, `AUTH_REJECTED`) y
`DEVICE_OFFLINE` (el dispositivo `DCG_ENTRANCE_DEVICE_CODE` no está `ONLINE` o lleva más de `DCG_DEVICE_OFFLINE_S`
sin latido). Para Registro 2 vale una solicitud vigente para **cualquier área** del centro: todas están detrás de la
entrada principal. `display_name` y `position` solo se devuelven si se concede.

Cada escaneo queda en la bitácora (`method: "QR"`), en la auditoría (`entrance.qr_granted` / `entrance.qr_denied`),
se emite por WebSocket (`entrance.scan`) y encola una señal para el LED de la entrada. Más de
`DCG_QR_SCAN_RATE_PER_MINUTE` (20) escaneos por minuto y cliente → `429 RATE_LIMITED` (no se registra).

### Dispositivo (ESP32, HMAC)

`POST /device/heartbeat`, `POST /device/presence`, `POST /device/access/start`,
`GET /device/access/{sid}?distance_cm=`, `POST /device/access/{sid}/opened`, `POST /device/access/{sid}/closed`
y `POST /device/event`. Contrato completo y firma de las respuestas en [protocolo-esp32.md](protocolo-esp32.md).

- `POST /device/exit-button`: botón de salida interior. Abre solo si hay alguien dentro de esa puerta (`NOBODY_INSIDE` en caso contrario), sin presencia, tarjeta ni rostro.
- `POST /device/presence` responde `{ok, alarm, alarm_s}`. `alarm:true` significa intrusión: el sensor interior detecta a alguien y no hay nadie autorizado dentro. Alerta `INTRUSION` CRITICAL.
- El poll con `GRANTED` añade `greeting` («Bienvenido» o «Hasta pronto») y `display_name` (nombre en ASCII) para el LCD.
- `POST /device/entrance/poll` (`{}`): `{signal: null}` o `{signal: {id, result: "GRANTED"|"DENIED", led_ms, display_name}}`.
  Cada señal se entrega **una sola vez**; si no se recoge en `DCG_ENTRANCE_SIGNAL_TTL_S` (10 s) queda `EXPIRADA`.
  `display_name` (ASCII, ≤ 40) solo va relleno en `GRANTED`. El LED verde es independiente del servo de la sala.
- `POST /device/entrance/{id}/ack` (`{shown: true}`): `{ok: true}`. Idempotente. `404 SIGNAL_NOT_FOUND` (otra puerta o
  id desconocido), `409 SIGNAL_NOT_DELIVERED` (pendiente o expirada).
- `POST /device/environment` (`{temperature_c, humidity_pct, sensor: "OK"|"ERROR"}`, cada 10 s): `{ok, fan, alarm}`.
  Ventilador desde `DCG_TEMP_HIGH_C` (27) hasta bajar de ese valor − 1 °C; alarma desde `DCG_TEMP_CRITICAL_C` (32) o con
  humedad fuera de [`DCG_HUMIDITY_LOW_PCT`, `DCG_HUMIDITY_HIGH_PCT`] (20–80 %). `sensor: "OK"` sin ambos valores cuenta
  como `ERROR`; con el sensor en error, `fan` y `alarm` son `false`.
- `heartbeat.config` incluye `temp_high_c`, `temp_critical_c`, `humidity_low_pct` y `humidity_high_pct`; `heartbeat.sensors`
  acepta `dht` (se muestra en `/devices/status/all`; su fallo se alerta como `SENSOR_DHT_ERROR`, no `SENSOR_FAULT`).

## Tiempo real — `WS /ws/events`

Autenticación: cookie de administrador o auditor (debe coincidir el `Origin`), o token de kiosco enviado en el **primer mensaje** `{"kiosk_token": "..."}`, nunca en la URL (el kiosco solo recibe `access.*`).
Formato: `{"type", "ts", "data"}`. Los eventos se publican **después del commit**.

| Evento | `data` |
|---|---|
| `access.awaiting_face` · `face_retry` · `face_ok` · `granted` · `opened` · `closed` · `denied` · `timeout` · `exit_requested` | Sesión de acceso (igual que `GET /access-sessions/{id}`) |
| `alert.created` · `alert.acknowledged` | Alerta |
| `device.status` · `device.presence` | Estado de hardware · cambio de presencia |
| `request.updated` | `{id, use_count}` al consumir una autorización |
| `entrance.scan` | Fila de bitácora del escaneo QR (igual que `GET /access-log`) |
| `environment` | Lectura del DHT11: `{device_code, area, temperature_c, humidity_pct, sensor, fan, alarm, conditions, at}` |

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
| `NOBODY_INSIDE` | Botón de salida pulsado sin nadie dentro | — |
| `QR_INVALID` · `QR_UNKNOWN` | QR con formato inválido · no registrado (entrada principal) | `UNKNOWN_QR` WARN (deduplicada 60 s) |
| `QR_REVOKED` · `QR_EXPIRED` · `QR_USED` | QR revocado · vencido · pase de un solo uso ya utilizado | `QR_BLOCKED` WARN |
| `DEVICE_OFFLINE` | El dispositivo de la entrada no está en línea | — (ya existe `DEVICE_OFFLINE`) |

Otras alertas:
- `INTRUSION` (CRITICAL): el sensor interior detecta a alguien y no hay nadie autorizado dentro; zumbador y LED rojo durante 20 s.
- `REPEATED_FAILURES` (CRITICAL): 3 fallos en 5 min con la misma tarjeta la bloquean 10 min.
- `DEVICE_AUTH_FAIL` (CRITICAL): firma, nonce o timestamp inválidos.
- `DEVICE_OFFLINE` (WARN): sin latido durante más de 45 s.
- `SENSOR_FAULT` (WARN).
- `DEVICE_EVENT`.
- `EMERGENCY_CLOSE`.
- Ambiente (DHT11), una sola vez mientras dure la condición y de nuevo cuando reaparece. El mensaje indica sensor, zona,
  fecha, valor y acción: `TEMPERATURA_ALTA` (WARN), `TEMPERATURA_CRITICA` (CRITICAL), `HUMEDAD_FUERA_DE_RANGO` (WARN) y
  `SENSOR_DHT_ERROR` (WARN).

## Frontend (contrato del shell)

- `import { api, ApiError, fmtDate, escapeHtml, toast, guarded } from "/js/api.js"`:
  - `api.get(path, query)`, `api.post`, `api.patch`, `api.del`, `api.upload(path, formData)`.
  - Las rutas son relativas a `/api/v1`. Un 401 redirige al login.
- Página: `<body data-page="clave"><main id="content">…</main>`. En su JS: `import { ready } from "/js/layout.js"; const admin = await ready;`.
- `/js/ws.js` exporta `connectEvents({kioskToken})` con `.on("access.*", fn)`. `/js/ui.js` contiene las tablas y etiquetas comunes y `reasonText(code)`.
- La clase `.admin-only` oculta las acciones de escritura a los auditores.
