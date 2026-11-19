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
| POST | `/device/presence` | `{present, distance_cm, threshold_cm}` | `{ok:true, alarm, alarm_s}` (§9) |
| POST | `/device/access/start` | `{uid, distance_cm, fw}` | `{session_id, state, poll_ms, timeout_s}` o `{state:"DENIED", reason_code}` (sin sesión) |
| GET | `/device/access/{sid}?distance_cm=30.1` | — | `{session_id, state, reason_code?, open_ms?, greeting?, display_name?}` |
| POST | `/device/exit-button` | `{source:"BUTTON"}` | Igual que `start`: `{session_id, state:"FACE_OK", poll_ms, timeout_s}` o `{state:"DENIED", reason_code:"NOBODY_INSIDE"}` |
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
| `GRANTED` en el poll | Abre solo si se cumplen **todas**: firma válida, `session_id` igual al de la sesión propia, `open_ms` entero en 1000–30000 y puerta `CLOSED`. Desde el 2026-11-15 ya **no** se exige presencia: el HC-SR04 está dentro de la sala (§9) |

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
- **Firmware: sin cambios.** `AWAITING_FACE` y `FACE_OK` ya son estados pendientes (§3), y `GRANTED` se valida con las mismas reglas de la §4.

```
ESP32                                   Backend                         Kiosco
  │ POST /device/access/start {uid} ────►│ ingeniero dentro ⇒ SALIDA       │
  │◄──── {session_id, AWAITING_FACE}      │── "verifique rostro" ─────────►│
  │ GET /device/access/{sid} ───────────►│◄── POST /vision/verify ─────────┤
  │◄──── {FACE_OK} … {GRANTED, open_ms}   │                                 │
  │ servo abre → /opened → /closed        │ cierra la presencia del ingeniero
```

## 8. Saludo en el LCD y botón de salida interior (2026-11-15)

### Saludo en `GRANTED`

La respuesta firmada de un poll con `state = GRANTED` incluye dos campos opcionales para la pantalla:

- `greeting`: `"Bienvenido"` en la entrada y `"Hasta pronto"` en la salida.
- `display_name`: el nombre del ingeniero transliterado a ASCII («José Ñúñez» → `Jose Nunez`), porque el HD44780 no tiene tildes. Máximo 40 caracteres, que el LCD reparte en dos líneas cortando por un espacio. Vacío si no se sabe quién es.

El firmware los trata como **texto no confiable**:
- Conserva solo ASCII imprimible (`sanitizeLcdText`).
- Los recorta a 20 y 40 caracteres.
- No los usa para ninguna decisión.

Pantalla del LCD: `ACCESO AUTORIZADO` / saludo / nombre (1 o 2 líneas). Se muestra 3 s antes de `PUERTA ABIERTA`.

### Botón de salida interior (GPIO 4)

El pulsador ya **no** es un cierre de emergencia local: es el **botón de salida desde dentro**.

1. El firmware lo filtra contra rebotes (50 ms) y llama a `POST /device/exit-button`. El botón nunca mueve el servo por sí mismo.
2. El backend abre **solo si hay alguien dentro de esa puerta**: un ingeniero cuyo último ciclo completo allí fue una ENTRADA en las últimas `DCG_EXIT_WINDOW_HOURS`.
   - **Nadie dentro:** `DENIED` / `NOBODY_INSIDE` y la puerta sigue cerrada.
   - **Una persona dentro:** sesión `SALIDA` a su nombre en estado `FACE_OK`. El siguiente poll da `GRANTED` con `greeting = "Hasta pronto"`. El cierre registra `access.exit`.
   - **Varias personas dentro:** abre igualmente, pero sin atribuir la salida a nadie, y genera una alerta INFO.
3. No exige tarjeta ni rostro: nadie queda atrapado. Tampoco depende del HC-SR04, que es un sensor interior de intrusión (§9).
4. **Sin conexión con el backend, el botón no abre**, porque no se puede comprobar si hay alguien dentro (fail-closed). La salida de emergencia ante un fallo eléctrico o de red debe resolverse con un desbloqueo mecánico de la cerradura.
5. El botón se ignora mientras hay otro intento en curso o la puerta no está cerrada.

El cierre de emergencia sigue disponible por dos vías: el comando remoto `EMERGENCY_CLOSE` (desde el panel) y el comando `close` de la consola serie.

## 9. HC-SR04 dentro de la sala: alarma de intrusión (2026-11-15)

El sensor ultrasónico **no está en la puerta, sino dentro de la sala**, así que ya **no es un factor de acceso**:
- La tarjeta se envía aunque no haya presencia.
- Una sesión no se deniega por distancia (dejan de usarse `PRESENCE_LOST` y `SENSOR_ERROR` en el acceso).
- `GRANTED` no exige presencia.

Su función ahora es detectar **intrusos**:

1. Cuando alguien entra en el radio del sensor (umbral configurable por dispositivo, `presence_threshold_cm`: 50 cm por defecto en la semilla; en la maqueta se usó 15 cm), el ESP32 envía `POST /device/presence {present:true, …}`.
2. El backend responde `{ok:true, alarm:true, alarm_s:20}` **solo si se cumplen las dos condiciones**:
   - nadie autorizado está dentro: ningún ingeniero tiene como último ciclo completo de esa puerta una ENTRADA;
   - la puerta no está en uso: ninguna sesión en `GRANTED`/`OPENED`, ni un ciclo terminado en los últimos `DCG_INTRUSION_DOOR_GRACE_S` (15 s), porque al entrar o salir se pasa por delante del sensor.

   En ese caso crea la alerta **`INTRUSION` (CRITICAL)**, con deduplicación de 20 s, y la registra en la auditoría como `device.intrusion`.
3. Con `alarm:true` el ESP32 hace parpadear el **LED rojo y el zumbador a la vez durante `alarm_s`** (20 s, entre 5 y 120). El LCD muestra `!!!!  ALARMA  !!!! / Intruso detectado / dentro de la sala`. La alarma **nunca mueve la puerta**.
4. **Sin conexión con el backend** (o si la petición falla) no se puede saber quién está dentro, así que suena la **alarma local** de 20 s (fail-secure). Excepción: los primeros 20 s tras el arranque, antes de conectar.
5. Que el sensor deje de responder sigue generando `SENSOR_FAULT` por el latido: es la alarma de intrusión la que deja de funcionar.


## 10. Señal de la entrada principal (código QR) (2026-11-17)

Contrato completo: [contrato-qr-dht11.md](contrato-qr-dht11.md) §2–§3. El mismo ESP32
(`DC-DOOR-01`) atiende la **entrada principal**, simulada con un LED verde en el GPIO 14. El
navegador del kiosco lee el QR (`POST /kiosk/entrance/scan`) y el backend decide y encola **una
señal** para el dispositivo. El ESP32 solo la muestra: no decide nada.

| Método | Ruta | Cuerpo | Respuesta 200 |
|---|---|---|---|
| POST | `/device/entrance/poll` | `{}` | `{signal: null}` o `{signal: {id, result: "GRANTED"\|"DENIED", led_ms, display_name}}` |
| POST | `/device/entrance/{id}/ack` | `{shown: true}` | `{ok: true}` |

Ambas peticiones van firmadas (§2.1) y sus respuestas deben llevar firma válida (§2.2).

### Funcionamiento en el firmware (`lib/dcg_core/src/entrance.*`)

- Consulta cada **1000 ms** desde el `loop()`. El servo vive en la tarea `io`, así que esta consulta nunca lo bloquea. También se hace con una sesión de la sala en curso.
- Por cada pasada del `loop()` se hace como mucho **una** llamada auxiliar (consulta de la entrada, ack o envío del DHT11). Se alternan para que ninguna se quede sin turno, y la sesión de la sala mantiene su ritmo.
- Tras un fallo (red, HTTP, firma o formato) espera 5 s antes de volver a consultar. Sin conexión con el backend (`OFFLINE`) no consulta.
- `GRANTED`: LED verde de la entrada encendido durante `led_ms`. El LCD muestra `ENTRADA PRINCIPAL` / `ACCESO QR OK` / nombre durante 3 s.
- `DENIED`: el LED rojo (GPIO 33) parpadea 3 veces (200 ms encendido / 200 ms apagado) y el zumbador da un pitido de 120 ms. El LCD muestra `ENTRADA PRINCIPAL` / `QR DENEGADO` durante 3 s.
- Después de mostrarla envía el **ack** en la siguiente pasada (hasta 3 intentos). La señal se muestra una sola vez aunque el ack falle.
- Si el LCD está en mitad de un ciclo de la sala (tarjeta, rostro o puerta en movimiento), conserva esa pantalla. El LED de la entrada se enciende igualmente.

### Validación (datos no confiables)

| Dato recibido | Regla |
|---|---|
| Respuesta sin firma, con firma inválida o fuera de ventana | Se ignora por completo: el LED sigue apagado y no se envía ack |
| `id` | Exactamente 32 hex en minúsculas. Se comprueba antes de ponerlo en la URL del ack; si no cumple, se descarta la señal |
| `result` | Solo `GRANTED` o `DENIED`. Cualquier otro valor se registra en la consola, se ignora y **no** se confirma |
| `led_ms` | Entero entre 1000 y 10000. Fuera de rango, decimal o texto ⇒ se descarta la señal. Si falta, 5000 |
| `display_name` | Texto no confiable: solo ASCII imprimible (`sanitizeLcdText`), como máximo 40 caracteres. Solo se usa en el LCD |
| Mismo `id` dos veces | Se ignora la segunda vez |

**Nunca mueve el servo de la sala.** La entrada y la sala de servidores son actuadores
independientes. El módulo de la entrada no tiene acceso a `openDoor` y las pruebas
(`test/test_entrance`) lo comprueban.

## 11. DHT11: temperatura y humedad de la sala (2026-11-17)

Contrato completo: [contrato-qr-dht11.md](contrato-qr-dht11.md) §4. El DHT11 (GPIO 16) mide la
temperatura y la humedad del **Servidor de clientes**.

| Método | Ruta | Cuerpo | Respuesta 200 |
|---|---|---|---|
| POST | `/device/environment` | `{temperature_c, humidity_pct, sensor: "OK"\|"ERROR"}` | `{ok: true, fan: bool, alarm: bool}` |

- Valores con 1 decimal. Con `sensor: "ERROR"` ambos valen `null`. Ejemplos: `{"temperature_c":24.5,"humidity_pct":51,"sensor":"OK"}` y `{"temperature_c":null,"humidity_pct":null,"sensor":"ERROR"}`.
- El latido añade `sensors.dht: "OK"|"ERROR"`. Mientras el sensor no haya fallado tres veces seguidas vale `"OK"`.
- `heartbeat.config` puede traer los umbrales. El firmware los acepta **por parejas** y solo si están en rango y son coherentes; si no, conserva la pareja anterior:

| Campo | Defecto | Rango aceptado |
|---|---|---|
| `temp_high_c` | 27 | 15–45 |
| `temp_critical_c` | 32 | 15–50 y mayor que `temp_high_c` |
| `humidity_low_pct` | 20 | 0–100 |
| `humidity_high_pct` | 80 | 0–100 y mayor que `humidity_low_pct` |

### Funcionamiento en el firmware (`lib/dcg_core/src/environment.*`)

- **Lectura cada 2 s** en una tarea FreeRTOS propia (`dht`, prioridad 1). Una lectura bloquea unos 25 ms, pero nunca a la tarea `io` (servo y HC-SR04) ni al `loop()`.
- Una lectura es válida solo si la suma de comprobación es correcta y los valores son razonables (−20 a 80 °C, 0 a 100 %).
- **3 lecturas fallidas seguidas**, o ninguna lectura en 10 s ⇒ sensor en `ERROR`. Una lectura válida lo recupera. El fallo del DHT11 **no** pone la puerta en `ERROR`: es un sensor ambiental y no interviene en el acceso.
- **Envío cada 10 s** de la última lectura válida, o de `ERROR`. No se envía nada hasta la primera lectura.
- Con una respuesta firmada y válida se aplican `fan` y `alarm`.
  - "Ante la duda se enfría": el ventilador queda encendido si lo pide el backend **o** si lo exige el umbral local. El backend no puede apagar un ventilador que los umbrales locales piden.
  - La decisión del backend caduca a los 25 s si no se renueva.
- **Respaldo local** si el backend no responde, la firma es inválida, falta `fan`/`alarm` (o no son booleanos) o el dispositivo está `OFFLINE`:
  - Ventilador: se enciende con `t ≥ temp_high_c` y se apaga con `t < temp_high_c − 1` (la misma histéresis que el backend).
  - Alarma: `t ≥ temp_critical_c` o humedad fuera de `[humidity_low_pct, humidity_high_pct]`.
- **Sensor en `ERROR`**: el ventilador se apaga (no hay dato que lo justifique) y el LCD muestra `TEMP/HUM: ERROR DHT`.
- **Alarma ambiental**: dos pitidos cortos cada 2 s (100 ms, pausa de 150 ms, 100 ms). Es distinto de la intrusión (§9: LED rojo y zumbador a 250 ms encendido / 250 ms apagado), y la intrusión tiene prioridad. En reposo el LCD muestra `ALARMA AMBIENTAL`, la lectura, la causa y el estado del ventilador.
- **LCD en reposo**: la línea 3 de `Esperando tarjeta` muestra `TEMP 24.5C HUM 51%`.
- Ventilador en el GPIO 2: LED amarillo, o relevador a través de un NPN (ver [cableado.md §8](cableado.md#8-ventilador-led-amarillo-o-relevador)).

### Consola serie

`status` añade una segunda línea: `dht=OK temp=24.5 hum=51.0 fan=0 env_alarm=0 env_local=0 entrance_led=0 thr_high=27.0 ...`.
El firmware de diagnóstico (`esp32dev-diag`) añade los comandos `dht`, `fan` y `qrled`.
