# Firmware de la puerta (ESP32) — DC Guardian

ESP32 + RC522 (RFID) + HC-SR04 (alarma de intrusión **dentro** de la sala) + servo SG90/MG996R
(cerradura) + botón de salida interior + DHT11 (temperatura/humedad, ventilador) + LED de la
entrada principal (señal del QR) + LCD 2004.
El dispositivo **no decide nunca el acceso**. Envía el UID de la tarjeta al backend, espera una
decisión `GRANTED` **firmada** y solo entonces mueve el servo. El HC-SR04 no es un factor de
acceso (protocolo §9) y la entrada principal solo enciende un LED, nunca el servo (§10).

- Protocolo: [`docs/protocolo-esp32.md`](../../docs/protocolo-esp32.md)
- Cableado, tabla de pines y alimentación: [`docs/cableado.md`](../../docs/cableado.md)

## 1. Estructura

```
firmware/esp32-door/
├── platformio.ini            entornos: esp32dev · esp32dev-bench · esp32dev-diag · native
├── include/
│   ├── pins.h                tabla de pines
│   └── dcg_config.example.h      → copiar a dcg_config.h (ignorado por git)
├── lib/dcg_core/src/         lógica PURA (sin Arduino), probada en el PC
│   ├── crypto.*              SHA-256/HMAC (mbedTLS en el ESP32, portable en el PC)
│   ├── signing.*             firma de peticiones y verificación de respuestas
│   ├── presence.*            mediana móvil + detección con confirmación e histéresis
│   ├── door.*                máquina CLOSED→OPENING→OPEN→CLOSING; OpenGrant
│   ├── protocol.*            JSON: construcción y validación (listas blancas, rangos)
│   ├── backend_client.*      cliente HTTP firmado (transporte inyectado)
│   ├── access_controller.*   máquina de estados principal
│   ├── environment.*         DHT11: salud del sensor, envío cada 10 s, ventilador y alarma (respaldo local)
│   ├── entrance.*            señal de la entrada principal (QR): consulta cada 1 s, LED y ack
│   └── lcd_view.*            qué muestra el LCD 2004 (máquina de estados de pantallas)
├── src/
│   ├── main.cpp              arranque, watchdog, consola serie
│   ├── hal_esp32.*           tarea FreeRTOS de E/S: servo, HC-SR04, botón, LEDs, ventilador; RC522; tarea DHT11
│   ├── net.*                 WiFi, NTP, RNG hardware, HTTPClient
│   ├── lcd_esp32.*           driver LCD 2004 I2C (PCF8574) en su propia tarea FreeRTOS
│   └── diag_main.cpp         firmware de diagnóstico (pruebas individuales)
├── test/                     pruebas unitarias (Unity) e integración (pytest)
└── tools/mock_gateway.py     gateway simulado del backend (Python, sin dependencias)
```

### Máquinas de estados

```
Sistema:  BOOT → IDLE ⇄ PRESENCE → CARD_READ → WAITING_DECISION → DOOR_OPEN → DOOR_CLOSING → IDLE
          (PRESENCE = alguien dentro de la sala según el HC-SR04; no condiciona el acceso)
          (botón de salida interior: CARD_READ → WAITING_DECISION por POST /device/exit-button)
          OFFLINE (sin WiFi, NTP o backend) / ERROR (fallo del RC522 o del HC-SR04) ⇒ tarjetas ignoradas, puerta cerrada
Puerta:   CLOSED → OPENING → OPEN → CLOSING → CLOSED   (+ cierre de emergencia remoto o por consola desde OPENING/OPEN)
Aparte:   entrada principal (EntrancePoller, LED GPIO 14) y DHT11 (EnvController, ventilador GPIO 2),
          independientes de la máquina de estados y de la puerta
```

## 2. Instalación

1. **PlatformIO**. En este repositorio ya está en `.tools/bin/pio`. En otro equipo:
   `pipx install platformio`, o la extensión de VS Code.
2. **Registrar el dispositivo** en el backend (como administrador):
   `POST /api/v1/devices {device_code: "DC-DOOR-01", name, area_id}`. Guarda el `secret`
   que devuelve: **solo se muestra una vez**. Si lo pierdes, usa la rotación de secreto.
3. **Configurar**:
   ```bash
   cd firmware/esp32-door
   cp include/dcg_config.example.h include/dcg_config.h
   ```
   Rellena WiFi, `DCG_BACKEND_URL` (la IP del PC en la LAN), `DCG_DEVICE_ID` y `DCG_DEVICE_SECRET`.
   `dcg_config.h` está en `.gitignore`: **nunca lo subas**.
4. **Backend accesible en la LAN**: `uvicorn app.main:app --host 0.0.0.0 --port 8000`.
   Abre el puerto 8000 en el cortafuegos del PC si hace falta.
5. **Compilar y flashear**:
   ```bash
   ../../.tools/bin/pio run -e esp32dev -t upload
   ../../.tools/bin/pio device monitor
   ```
   Si el puerto serie da `Permission denied` en Linux, añade tu usuario al grupo `dialout` y vuelve a iniciar sesión.

Al arrancar, el servo va a 0° (cerrado) **antes** de conectar a la red. Si la configuración es
inválida (secreto de ejemplo, URL mal escrita, `https://` sin CA), el dispositivo no opera.

### Consola serie (115200 baudios)

| Comando | Efecto |
|---|---|
| `status` | Estado, puerta, ángulo, distancia, umbral, RFID, WiFi, NTP, sesión; segunda línea con DHT11, ventilador, alarma ambiental y LED de la entrada |
| `close` | Cierre de emergencia local (motivo `LOCAL_BUTTON`). El pulsador del GPIO 4 **no** cierra: es el botón de salida interior (protocolo §8). **No existe un comando para abrir** |
| `uid <HEX>` · `dist <cm>` / `dist off` | Solo en `esp32dev-bench`: simula una tarjeta o una distancia |

## 3. Seguridad (resumen)

| Medida | Dónde |
|---|---|
| El UID **no es un secreto** (MIFARE se clona). Solo identifica la tarjeta: el backend exige además una autorización vigente (Registro 2) y el rostro. El HC-SR04 está dentro de la sala y no interviene | `access_controller.cpp` |
| Peticiones firmadas con HMAC-SHA256 + timestamp + nonce aleatorio de 16 bytes | `signing.cpp`, `backend_client.cpp` |
| **Respuestas firmadas y ligadas al nonce**: las falsificadas, reinyectadas o sin firma se rechazan | `verifyResponse` |
| Solo se abre con un `GRANTED` válido de la **propia sesión**, con `open_ms` en rango y la puerta cerrada (sin requisito de presencia) | `handleWaiting` |
| Botón de salida interior: pide permiso al backend (`/device/exit-button`), que abre solo si hay alguien dentro; sin conexión no abre | `requestExitByButton` |
| Señal de la entrada (QR) y DHT11: respuestas sin firma o inválidas se ignoran (LED apagado; ventilador y alarma en respaldo local). Ninguno de los dos mueve el servo | `entrance.cpp`, `environment.cpp` |
| `OpenGrant` tiene constructor privado: solo el controlador puede abrir la puerta | `door.h` |
| Lista blanca de comandos remotos: solo `EMERGENCY_CLOSE` | `protocol.cpp` |
| Timeouts: 3 s por HTTP, sesión `timeout_s` + 2 s, 3 errores ⇒ abortar | `ControllerTiming` |
| Desconexión (WiFi, backend o NTP) ⇒ `OFFLINE`: se cierra la puerta si estaba abierta y se ignoran las tarjetas | `tick()` |
| La puerta se cierra sola por temporizador local, aunque se pierda la red | `door.cpp` (tarea de E/S) |
| Watchdog de 15 s: si se cuelga, se reinicia y el servo vuelve a CERRADO | `main.cpp` |
| No se siguen redirecciones HTTP; respuestas > 4 KiB rechazadas; `session_id` validado antes de ir en la URL | `net.cpp`, `protocol.cpp` |

Limitaciones conocidas: sin HTTPS (opcional), un atacante en la LAN puede **ver** el tráfico,
pero no falsificarlo ni reinyectarlo. El secreto está en la flash del ESP32 sin cifrar: quien tenga
acceso físico a la placa puede extraerlo. Para mitigarlo, rota el secreto si pierdes un dispositivo.
Los entornos `bench` y `diag` **no** deben usarse en una puerta real.

## 4. Pruebas

### 4.1 Pruebas unitarias (PC, sin hardware)

```bash
cd firmware/esp32-door
../../.tools/bin/pio test -e native
```

| Suite | Qué demuestra |
|---|---|
| `test_signing` | SHA-256 y HMAC (vectores NIST y RFC 4231); firma **idéntica byte a byte** a `backend/app/core/security.py` (vectores generados con él); se detectan respuestas manipuladas, reinyectadas, sin firma y caducadas |
| `test_presence` | La mediana descarta picos; hacen falta 3 lecturas seguidas; histéresis de 5 cm; umbral configurable (2–400); fallo del sensor ⇒ sin presencia |
| `test_door` | Ciclo completo con eventos; rechaza `open_ms` fuera de rango; no reabre ni prolonga; el cierre de emergencia invierte el movimiento desde el ángulo actual |
| `test_protocol` | Validación de `session_id` y UID; configuración fuera de rango ignorada; comandos `OPEN`/`REBOOT` ignorados; `GRANTED` malformado rechazado |
| `test_backend_client` | Petición firmada correctamente; nonces únicos; rechaza clave errónea, cuerpo alterado, respuesta reinyectada o caducada; sin NTP no se envía nada |
| `test_lcd` | Pantalla correcta para cada estado (esperando tarjeta, presencia y distancia, RFID, verificando, rostro, concedido, denegado con motivo, puerta abierta/cerrada, error de conexión, desconectado); 4 líneas de 20 caracteres ASCII en todas las pantallas |
| `test_environment` | DHT11: 3 fallos seguidos ⇒ `ERROR` y ventilador apagado; envío cada 10 s; `{fan, alarm}` firmado aplicado; firma inválida, error o sin conexión ⇒ respaldo local con histéresis de 1 °C; el backend no puede apagar un ventilador necesario; umbrales incoherentes rechazados; nunca toca la puerta |
| `test_entrance` | Señal QR: consulta cada 1 s; `GRANTED` ⇒ LED de la entrada `led_ms` y ack; `DENIED` ⇒ parpadeo rojo y ack; resultado desconocido, firma inválida o formato erróneo ⇒ ignorada sin ack; la misma señal no se muestra dos veces; **nunca mueve el servo** |
| `test_controller` | Flujo completo con confirmaciones; tarjeta sola ⇒ no abre; DENIED, error de red o firma inválida ⇒ cerrada; GRANTED de otra sesión ⇒ cerrada; la tarjeta se envía y el GRANTED se aplica sin presencia (sensor interior); alarma de intrusión (backend, local sin conexión, no en el arranque); botón de salida (abre solo con sesión del backend, ignorado sin conexión o con otro intento); DHT11 en `ERROR` no bloquea la puerta; caída de WiFi ⇒ OFFLINE y cierre; configuración remota; cierres de emergencia remoto y local |

### 4.2 Pruebas de integración (PC: firmware real ↔ gateway por HTTP)

El núcleo del firmware se compila para el PC (`test/host/host_runner.cpp`, sockets POSIX) y
habla por HTTP real con `tools/mock_gateway.py`, que es una implementación independiente del
protocolo. Solo se simula el hardware: una persona a 30 cm presenta una tarjeta.

```bash
../../.tools/bin/pio test -e native          # una vez: descarga ArduinoJson
../../backend/.venv/bin/pytest test/integration -v
```

| Escenario | Resultado esperado |
|---|---|
| `grant` | 1 apertura, 90°, `opened` → `closed:TIMER`, distancia firmada en la query |
| `deny`, `unknown`, `never` | Puerta a 0° en todo momento |
| `badsig`, `unsigned`, `replay`, `othersid` | Puerta a 0°; evento `BAD_RESPONSE_SIGNATURE` |
| Secreto erróneo / backend caído | `OFFLINE`, sin apertura |
| `emergency` | Abre y se cierra por `EMERGENCY_CLOSE` antes de `open_ms` |
| Contrato | La firma del mock es igual a la de `security.py` del backend |

### 4.3 Pruebas individuales del hardware (firmware de diagnóstico)

⚠ Este firmware puede mover el servo por comando: úsalo con el servo **desacoplado** de la puerta.

```bash
../../.tools/bin/pio run -e esp32dev-diag -t upload && ../../.tools/bin/pio device monitor
```

| # | Componente | Comando | Criterio de aceptación |
|---|---|---|---|
| H1 | RC522 | `info` | `VersionReg=0x91` o `0x92` (`0x00`/`0xFF` ⇒ revisa el cableado y los 3.3 V) |
| H2 | RC522 | `rfid` | Cada tarjeta imprime un UID estable (mismo valor en 5 lecturas) y no se repite mientras sigue apoyada |
| H3 | HC-SR04 | `dist` | Con un objeto a 30 cm: mediana 30 ± 2 cm; sin objeto: `present=0`; tapar el sensor no genera picos |
| H4 | HC-SR04 | `dist` | Acercarse a menos de 50 cm ⇒ `present=1` tras unas 3 lecturas; alejarse a más de 55 cm ⇒ `present=0` |
| H5 | Servo | `servo 0`, `servo 90`, `sweep` | Recorrido suave sin zumbido ni reinicio del ESP32 (si se reinicia: §3 de cableado) |
| H6 | Botón | `button` | `PULSADO`/`suelto` sin rebotes múltiples |
| H7 | LEDs/zumbador | `led`, `buzz` | Verde y luego rojo; pitido breve |

### 4.4 Pruebas de integración con el ESP32 real

**Con el gateway simulado** (sin backend completo). En el PC:

```bash
python3 tools/mock_gateway.py --secret <DCG_DEVICE_SECRET> --port 8000 --scenario grant
```

Flashea `esp32dev` con `DCG_BACKEND_URL` apuntando al PC. Cambia de escenario en caliente con:

```bash
curl -X POST localhost:8000/mock/scenario -d '{"scenario":"deny"}'
```

| # | Prueba | Pasos | Resultado esperado |
|---|---|---|---|
| I1 | Conexión | Encender | `backend ONLINE`; heartbeats en el log del mock; LED verde parpadeando |
| I2 | Umbral remoto | `--threshold-cm 80` y reiniciar el mock | `presence threshold = 80 cm` en la consola |
| I3 | Acceso concedido | `grant`: acercarse y pasar tarjeta | Abre unos 5 s, se cierra sola; `opened`/`closed TIMER` en el mock |
| I4 | Tarjeta sin presencia | Pasar tarjeta sin nadie ante el HC-SR04 | La tarjeta se envía igual (`start` en el mock): el sensor está dentro de la sala y no es un factor de acceso |
| I5 | Denegado | `deny` | LED rojo y pitidos; puerta cerrada |
| I6 | Respuesta falsificada | `badsig`, `unsigned`, `replay` | Puerta cerrada; `response BAD_SIGNATURE` en la consola |
| I7 | Timeout | `never` | Unos 12 s después: `session aborted: TIMEOUT`; puerta cerrada |
| I8 | Corte de red | Parar el mock con la puerta cerrada | `OFFLINE` en unos 45 s; LED rojo parpadeando; las tarjetas se ignoran |
| I9 | Corte con la puerta abierta | `--open-ms 20000`, abrir y parar el mock | Se cierra (EMERGENCY) al detectar OFFLINE, a más tardar con el temporizador |
| I10 | Emergencia remota | `emergency` con `--open-ms 20000` | Se cierra en ≤ 2 s tras abrirse; `closed EMERGENCY` |
| I11 | Emergencia local | Abrir y escribir `close` en la consola | Cierre inmediato; `closed LOCAL_BUTTON` |
| I11b | Botón de salida | Pulsar el botón del GPIO 4 con la puerta cerrada | `exit button -> backend`. El mock no implementa `/device/exit-button` (404 firmado) ⇒ intento abortado, puerta cerrada. Con el backend real abre solo si hay alguien dentro |
| I14 | Entrada principal (QR) | `curl -X POST localhost:8000/mock/entrance -d '{"result":"GRANTED","led_ms":3000}'` (o `DENIED`) | LED del GPIO 14 encendido 3 s y LCD `ACCESO QR OK` (o rojo ×3 + pitido y `QR DENEGADO`); `entrance_ack` en el mock; el servo no se mueve |
| I15 | DHT11 | Calentar el sensor con la mano o desconectar DATA | `environment` cada 10 s en el mock; ventilador (GPIO 2) a partir de 27 °C; desconectado: `TEMP/HUM: ERROR DHT`, ventilador apagado y `sensors.dht = ERROR` |
| I16 | Intrusión | Ponerse ante el HC-SR04 sin conexión con el backend (más de 20 s tras arrancar) | Alarma local 20 s: LED rojo y zumbador a 250 ms. El mock responde `presence` sin `alarm`, así que con él conectado no suena |
| I12 | Reinicio con la puerta abierta | Abrir y pulsar EN/RST | Al arrancar, el servo vuelve a 0° |
| I13 | Watchdog/NTP | Bloquear el NTP del router | El dispositivo no sale de OFFLINE (no firma sin hora válida) |

**Con el backend real**, cuando exista el gateway F5: mismas pruebas, más el flujo completo
del kiosco facial. Usa una solicitud `APROBADA` vigente para I3 y casos de `reason_code`
reales: tarjeta no vinculada, solicitud expirada, rostro que no coincide.
