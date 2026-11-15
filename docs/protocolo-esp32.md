# Protocolo ESP32 ↔ Backend (DC Guardian)

> **Fuente de verdad** del contrato entre el firmware (`firmware/esp32-door`) y el gateway
> del backend (`/api/v1/device/*`). Amplía la §5 de `FASE1_ARQUITECTURA.md`. Lo acordaron
> la sesión de firmware y la de integración el 2026-11-14.
> Implementación de referencia en Python: `firmware/esp32-door/tools/mock_gateway.py`.

## 1. Transporte

- HTTP/1.1 sobre WiFi (HTTPS opcional con CA fijada en `dcg_config.h`). Sin MQTT: lo descartó la §2.2 del diseño.
- El ESP32 solo actúa como **cliente**: no abre ningún puerto y no recibe órdenes entrantes.
  Las "órdenes" llegan únicamente como respuesta a sus propias peticiones.
- Timeout por petición: 3 s. No se siguen redirecciones. Las respuestas de más de 4 KiB se rechazan.
- Cuerpos JSON compactos. La firma se calcula sobre los **bytes exactos** enviados.
- Límites del gateway: un cuerpo de petición de más de 4 KiB recibe `413`, **sin firma** (se corta antes de autenticar). Una query con parámetros duplicados recibe `400 DEVICE_BAD_QUERY`, **firmado**. El firmware nunca provoca ninguno de los dos: sus cuerpos son de menos de 300 B y solo envía `distance_cm` una vez.

## 2. Autenticación

### 2.1 Petición (dispositivo → backend)

```
X-Device-Id:  DC-DOOR-01
X-Timestamp:  1763130000            epoch s (NTP), tolerancia ±DCG_DEVICE_CLOCK_SKEW_S (30 s)
X-Nonce:      32 hex                16 bytes del RNG hardware, único por petición
X-Signature:  hex(HMAC_SHA256(secret, METHOD \n PATH \n CANONICAL_QUERY \n TS \n NONCE \n sha256hex(body)))
```

- `secret`: el secreto de 64 caracteres hex que devuelve `POST /devices`. La clave HMAC son
  **sus bytes ASCII** y no el valor hex decodificado (igual que `security.hmac_sign`).
- `PATH`: la ruta sin query (`/api/v1/device/access/<sid>`).
- `CANONICAL_QUERY`: `urlencode(sorted(pares))` de Python (`quote_plus`, espacio → `+`); vacío si no hay query.
- Implementado en `security.device_signing_string` (backend) y en `signing.cpp` (firmware).
  Hay vectores de prueba compartidos en `test/test_signing`.

### 2.2 Respuesta (backend → dispositivo)

**Todas** las respuestas `/device/*`, incluidas 4xx/5xx, llevan:

```
X-Timestamp:  epoch s del servidor
X-Signature:  hex(HMAC_SHA256(secret, "RESP" \n METHOD \n PATH \n NONCE_DE_LA_PETICIÓN \n HTTP_STATUS \n TS \n sha256hex(body)))
```

- La firma queda ligada al **nonce de la petición**. Una respuesta `GRANTED` capturada no se puede reinyectar en otra petición.
- También autentica la configuración y los comandos del heartbeat.
- Backend: `security.device_response_signing_string(method, path, request_nonce, status, ts, body)`.
- Si el `X-Device-Id` es desconocido no hay secreto con el que firmar. En ese caso el 401 va sin firma y el ESP32 lo descarta.

El ESP32 **rechaza** una respuesta sin firma, con firma inválida o con `X-Timestamp` fuera de ±30 s.
La trata igual que un fallo de red: fail-closed.

## 3. Endpoints

| Método | Ruta | Cuerpo de la petición | Respuesta 200 |
|---|---|---|---|
| POST | `/device/heartbeat` | `{fw, state, door, present, distance_cm, rssi, uptime_s, free_heap, session_id, sensors:{rfid:"OK"\|"ERROR", ultrasonic:"OK"\|"TIMEOUT"}}` | `{server_time, config:{presence_threshold_cm, door_open_ms, heartbeat_s}, command: null\|"EMERGENCY_CLOSE"}` |
| POST | `/device/presence` | `{present, distance_cm, threshold_cm}` | `{ok:true}` |
| POST | `/device/access/start` | `{uid, distance_cm, fw}` | `{session_id, state, poll_ms, timeout_s}` o `{state:"DENIED", reason_code}` (sin sesión) |
| GET | `/device/access/{sid}?distance_cm=30.1` | — | `{session_id, state, reason_code?, open_ms?}` |
| POST | `/device/access/{sid}/opened` | `{open_ms}` | `{ok:true}` |
| POST | `/device/access/{sid}/closed` | `{reason:"TIMER"\|"EMERGENCY"\|"LOCAL_BUTTON"}` | `{ok:true}` |
| POST | `/device/event` | `{type, detail}`. Tipos: `BAD_RESPONSE_SIGNATURE`, ... | `{ok:true}` |

Formatos:

- `uid`: hex en mayúsculas sin separadores (`04A1B2C3`), igual que `normalize_uid`.
- `session_id`: 32 hex en minúsculas (`uuid4().hex`). El firmware valida el formato antes de ponerlo en la URL.
- `distance_cm`: 1 decimal (`%.1f` en la query, número en JSON). Vale `-1` si no hay lectura válida.
- `state` (sesión): `CARD_READ`, `AWAITING_FACE` y `FACE_OK` se consideran pendientes; `GRANTED` es el único que abre; cualquier otro (`DENIED`, `TIMEOUT`...) termina la sesión.
- `reason_code`: `UNKNOWN_CARD`, `CARD_NOT_ACTIVE`, `CARD_LOCKED`, `CARD_NOT_LINKED`,
  `ENGINEER_INACTIVE`, `NO_VALID_AUTH`, `REQUEST_PENDING`, `AUTH_EXPIRED`, `AUTH_REVOKED`,
  `AUTH_NOT_STARTED`, `NO_FACE_ENROLLED`, `FACE_MISMATCH`, `LIVENESS_FAILED`, `PRESENCE_LOST`,
  `SENSOR_ERROR`, `DEVICE_DISABLED`, `TIMEOUT`.

## 4. Reglas del firmware (validación de datos no confiables)

| Dato recibido | Regla |
|---|---|
| `config.presence_threshold_cm` | Se aplica solo si está en 2–400 cm; si no, se conserva el valor anterior (por defecto 50) |
| `config.door_open_ms` | 1000–30000 ms |
| `config.heartbeat_s` | 5–60 s |
| `command` | Lista blanca: solo `EMERGENCY_CLOSE`. Cualquier otro valor se ignora y se registra. **No existe un comando para abrir** |
| `poll_ms` / `timeout_s` | Se limitan a 300–2000 ms y 5–60 s |
| `GRANTED` en `start` | Se rechaza: una sesión nueva nunca puede estar concedida |
| `GRANTED` en el poll | Abre solo si se cumplen **todas**: firma válida, `session_id` igual al de la sesión propia, `open_ms` entero en 1000–30000, presencia local en ese instante y puerta `CLOSED` |

## 5. Temporización

| Evento | Periodo |
|---|---|
| Heartbeat | `heartbeat_s` (15 s), cada 2 s mientras la puerta no está `CLOSED` y cada 5 s mientras está `OFFLINE` |
| Paso a `OFFLINE` | 3 heartbeats fallidos seguidos, WiFi caída o reloj sin NTP |
| Poll de decisión | `poll_ms`. La sesión se aborta tras 3 errores seguidos o al cumplirse `timeout_s` + 2 s |
| Confirmación `opened`/`closed` | Hasta 5 intentos cada 2 s, en orden |
| Misma tarjeta | Se ignora durante 3 s (antirrebote) |

## 6. Secuencia

```
ESP32                                   Backend
  │ POST /device/heartbeat ─────────────►│  (al arrancar y periódicamente)
  │◄──────────── config + command, firmado│
  │ HC-SR04: presencia (3 lecturas ≤ umbral)
  │ POST /device/presence ──────────────►│
  │ RC522: UID
  │ POST /device/access/start ──────────►│ valida tarjeta, vínculo, ingeniero, Registro 2
  │◄──── {session_id, AWAITING_FACE}      │
  │ GET /device/access/{sid}?distance ──►│ (cada poll_ms) ← kiosco: verificación facial
  │◄──── {GRANTED, open_ms} firmado       │
  │ servo: CLOSED→OPENING→OPEN
  │ POST …/opened ──────────────────────►│
  │ (open_ms) OPEN→CLOSING→CLOSED
  │ POST …/closed {reason:"TIMER"} ─────►│
```

## 7. Salida (segunda pasada de tarjeta)

Con un solo lector, la salida usa el mismo flujo que la entrada. Si el ingeniero de la tarjeta
figura dentro del área, el backend trata la sesión como `SALIDA`:

- **Exige rostro en el kiosco**, igual que la entrada. Con un solo lector, una tarjeta clonada o prestada abriría desde fuera sin esta verificación. Cambio del 2026-11-14, tras la revisión de seguridad.
- **No exige** una autorización vigente (Registro 2): nadie queda atrapado dentro aunque su solicitud haya vencido o la hayan revocado.
- Estados: `start` → `AWAITING_FACE`; poll → `AWAITING_FACE` → `FACE_OK` → `GRANTED`.
- **Firmware: sin cambios.** `AWAITING_FACE` y `FACE_OK` ya son estados pendientes (§3), y `GRANTED` se valida con las mismas reglas de la §4, incluida la presencia local.

```
ESP32                                   Backend                         Kiosco
  │ POST /device/access/start {uid} ────►│ ingeniero dentro ⇒ SALIDA       │
  │◄──── {session_id, AWAITING_FACE}      │── "verifique rostro" ─────────►│
  │ GET /device/access/{sid} ───────────►│◄── POST /vision/verify ─────────┤
  │◄──── {FACE_OK} … {GRANTED, open_ms}   │                                 │
  │ servo abre → /opened → /closed        │ cierra la presencia del ingeniero
```
