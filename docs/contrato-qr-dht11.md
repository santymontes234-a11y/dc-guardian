# Contrato: acceso QR en la entrada principal + DHT11 (Telecom Conecta, Parcial 3)

> Fuente de verdad compartida por backend, firmware, simulador y frontend (2026-11-17).
> Amplía `protocolo-esp32.md` (§10 y §11). Toda petición `/device/*` nueva usa la autenticación
> HMAC de la §2 de ese documento y su respuesta va firmada. Fail-closed en todo momento.

## 0. Escenario

Empresa asignada: **Telecom Conecta**. Zona crítica: **Servidor de clientes**.
Roles (campo `engineers.position`): `Administrador de TI`, `Ingeniero de red`,
`Personal de limpieza`, `Proveedor`.

| Código de área | Nombre | Métodos |
|---|---|---|
| `ENTRADA_PRINCIPAL` | Entrada principal / recepción | Código QR (webcam en navegador) → LED verde |
| `SALA_SERVIDORES` | Sala de servidores (Servidor de clientes) | Tarjeta RFID RC522 + reconocimiento facial → servo SG90 |

Un solo ESP32 (`DC-DOOR-01`) atiende las dos puertas de la maqueta. La entrada principal se
simula con un **LED verde** (puerta abierta) y un parpadeo del LED rojo existente (denegado).

## 1. Pines nuevos (ESP32 DevKit v1)

| Elemento | GPIO | Notas |
|---|---|---|
| DHT11 (DATA) | 16 | Pull-up de 10 kΩ a 3.3 V (el módulo de 3 pines ya lo trae). VCC 3.3 V |
| LED verde de la entrada principal | 14 | 220 Ω a GND. Distinto del `PIN_LED_GREEN` (25) de la sala |
| Ventilador (LED amarillo o relevador) | 2 | 220 Ω. Relevador solo a través de un transistor NPN. El LED integrado también se enciende |

## 2. Credencial QR

- Texto del QR: `DCG-QR1:<token>`, con `token = secrets.token_urlsafe(24)` (32 caracteres).
- En la base solo se guarda `sha256(token)` y un prefijo de 6 caracteres para mostrarlo. El texto
  completo se devuelve **una sola vez**, al emitirlo.
- Hay una credencial `ACTIVA` por ingeniero como máximo. Emitir una nueva revoca la anterior.
- Estados: `ACTIVA`, `REVOCADA`. Si `expires_at` es nulo, la credencial no vence.

### API administrativa (requiere JWT de admin)

| Método | Ruta | Respuesta |
|---|---|---|
| POST | `/api/v1/engineers/{id}/qr` | `201 {qr_text, prefix, expires_at, engineer:{id, full_name, position}}` |
| GET | `/api/v1/engineers/{id}/qr` | `{active: bool, prefix, created_at, expires_at, last_used_at}` (sin token) |
| DELETE | `/api/v1/engineers/{id}/qr` | `204`: revoca |

### Escaneo en la entrada (autenticación de kiosco, igual que `/kiosk/*`)

`POST /api/v1/kiosk/entrance/scan`, cuerpo `{qr_text}`.

Respuesta 200:
```
{result: "GRANTED"|"DENIED", reason_code?, display_name?, position?, area: "ENTRADA_PRINCIPAL", event_id}
```

Validación en este orden; el primer fallo da `DENIED`:

| Fallo | `reason_code` |
|---|---|
| Formato inválido | `QR_INVALID` |
| No existe | `QR_UNKNOWN` |
| La credencial no está activa | `QR_REVOKED` |
| La credencial venció | `QR_EXPIRED` |
| Ingeniero no `ACTIVO` | `ENGINEER_INACTIVE` |
| Sin autorización `APROBADA` vigente ahora (Registro 2). Se usan los mismos códigos que el motor | `NO_VALID_AUTH`, `AUTH_NOT_STARTED`, `AUTH_EXPIRED`, … |
| El dispositivo de la entrada (`DCG_ENTRANCE_DEVICE_CODE`, por defecto `DC-DOOR-01`) no está `ONLINE` | `DEVICE_OFFLINE` |

Reglas adicionales:
- Límite de 20 escaneos por minuto por cliente. Si se supera: `429`.
- Cada escaneo, concedido o denegado, se registra en la bitácora con fecha y hora, persona (si se conoce), zona `ENTRADA_PRINCIPAL`, método `QR` y resultado. También va a `audit.record` y al WebSocket del dashboard.
- Un resultado `GRANTED` o `DENIED` encola una **señal** para el dispositivo de la entrada.

## 3. Dispositivo: señal de la entrada (`protocolo-esp32.md` §10)

| Método | Ruta | Cuerpo | Respuesta 200 |
|---|---|---|---|
| POST | `/device/entrance/poll` | `{}` | `{signal: null}` o `{signal: {id, result:"GRANTED"\|"DENIED", led_ms, display_name}}` |
| POST | `/device/entrance/{id}/ack` | `{shown: true}` | `{ok: true}` |

Formato de los campos:
- `id`: 32 caracteres hex en minúsculas.
- `led_ms`: entre 1000 y 10000 ms. Por defecto 5000.
- `display_name`: ASCII, como máximo 40 caracteres, y se trata como **texto no confiable**.

Funcionamiento:
- La señal se entrega **una sola vez**: el poll la marca como entregada.
- Una señal que no se entrega en 10 s caduca, se descarta y queda registrada como `EXPIRADA`.
- El firmware hace poll cada 1000 ms. Puede hacerlo mientras hay una sesión de la sala, pero sin bloquear el control del servo.

Acciones del firmware según `result`:
- `GRANTED`: enciende el LED verde de la entrada (GPIO 14) durante `led_ms`. El LCD muestra `ENTRADA PRINCIPAL` / `ACCESO QR OK` / nombre durante 3 s.
- `DENIED`: el LED rojo parpadea 3 veces, el buzzer da un pitido corto y el LCD muestra `ENTRADA PRINCIPAL` / `QR DENEGADO`.
- Cualquier otro valor se ignora y se registra.

Restricciones:
- Esto **no** abre el servo de la sala de servidores: son actuadores independientes.
- Si una respuesta no viene firmada o su firma es inválida, se ignora por completo (fail-closed: el LED sigue apagado).

## 4. Dispositivo: DHT11 (`protocolo-esp32.md` §11)

`POST /device/environment`, cada 10 s, cuerpo `{temperature_c, humidity_pct, sensor:"OK"|"ERROR"}`.
Los valores numéricos llevan 1 decimal; si `sensor` es `"ERROR"` valen `null`.

Respuesta 200: `{ok:true, fan: bool, alarm: bool}`.

`heartbeat.config` añade estos campos; el firmware solo los acepta si están dentro de rango:

| Campo | Defecto | Rango aceptado |
|---|---|---|
| `temp_high_c` | 27 | 15–45 |
| `temp_critical_c` | 32 | 15–50, y mayor que `temp_high_c` |
| `humidity_low_pct` | 20 | 0–100 |
| `humidity_high_pct` | 80 | 0–100, y mayor que `humidity_low_pct` |

Además, `heartbeat.sensors` añade `dht: "OK"|"ERROR"`.

### Backend

Configuración: variables `DCG_TEMP_HIGH_C`, `DCG_TEMP_CRITICAL_C`, `DCG_HUMIDITY_LOW_PCT`, `DCG_HUMIDITY_HIGH_PCT` y `DCG_ENTRANCE_DEVICE_CODE`.

Lógica de cada lectura:
- Guarda cada lectura en `environment_readings` (dispositivo, área `SALA_SERVIDORES`, valores, estado y fecha UTC) y purga las de más de 7 días.
- Pide `fan = true` cuando la temperatura llega a `temp_high_c` o más. Lo apaga cuando baja de `temp_high_c - 1` (histéresis).
- Pide `alarm = true` cuando la temperatura llega a `temp_critical_c` o más, o cuando la humedad sale de rango.

Alertas, sin repetirse mientras la condición persista. La alerta se re-arma cuando la condición desaparece:

| Alerta | Severidad |
|---|---|
| `TEMPERATURA_ALTA` | WARN |
| `TEMPERATURA_CRITICA` | CRITICAL |
| `HUMEDAD_FUERA_DE_RANGO` | WARN |
| `SENSOR_DHT_ERROR` | WARN |

Cada lectura se emite por WebSocket como un evento `environment`.

Consulta (JWT de admin o auditor):
- `GET /api/v1/monitoring/environment/latest` → `{device_code, area, temperature_c, humidity_pct, sensor, fan, alarm, at, thresholds:{...}}`
- `GET /api/v1/monitoring/environment?minutes=60` → `{items:[{at, temperature_c, humidity_pct}]}` (como máximo 1440 puntos)

### Firmware

Lectura del sensor:
- Lee el DHT11 cada 2 s. Envía la última lectura válida cada 10 s.
- Tras 3 lecturas fallidas seguidas, el sensor pasa a `ERROR`.

Respaldo local, para que el sistema siga siendo seguro sin backend:
- Si el backend no responde o la firma es inválida, el firmware decide el ventilador por su cuenta con `temp_high_c` y la misma histéresis. Ante la duda se enfría.
- Con el sensor en `ERROR`, el ventilador se apaga y el LCD muestra el error.

Alarma:
- Con `alarm` activa, el buzzer suena con un patrón intermitente distinto del de intrusión.
- El LCD muestra `TEMP xx.xC HUM yy%` en la pantalla de reposo.

## 5. Simulador (`simulator/esp32_sim.py`, `backend/app/api/v1/sim.py`)

`SimDevice` añade estos métodos:
- `environment(temperature_c, humidity_pct, sensor="OK")` → `Reply` (aplica `fan` y `alarm` al estado simulado).
- `entrance_poll()` → `Reply` (si llega una señal, actualiza `entrance_led` a `"GREEN"` o `"RED_BLINK"` con su vencimiento y envía el ack).
- Propiedades de estado: `entrance_led`, `fan`, `env_alarm`, `last_env`.

`sim.py` (solo con `DCG_SIMULATION=true`) añade:
- `POST /sim/{code}/environment` `{temperature_c, humidity_pct, sensor}`
- `POST /sim/{code}/entrance-poll`

Y `GET /sim/state` incluye por dispositivo `entrance_led`, `fan`, `env_alarm` y `last_env`.

## 6. Bitácora

`GET /api/v1/access-log` (o el endpoint de bitácora existente) expone por fila:
`at`, `person` (nombre o `null`), `position`, `zone` (código y nombre del área), `method`
(`QR` o `RFID+ROSTRO`), `direction` y `result` (`GRANTED`/`DENIED` + `reason_code`).

Las alarmas de sensores aparecen en las alertas con sensor, zona, fecha, valor y acción.
