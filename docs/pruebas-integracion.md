# Pruebas de integración (F8)

Fecha: 2026-11-14. Cadena probada: **ESP32 (firmado) → gateway `/device/*` → motor de acceso → kiosco 1:1 →
auditoría / alertas / WebSocket / panel**.

## Cómo ejecutarlas

```bash
cd backend && .venv/bin/pytest                    # suite completa (incluye tests/e2e)
cd backend && .venv/bin/pytest tests/e2e -v       # solo los flujos de integración
cd firmware/esp32-door && ../../backend/.venv/bin/pytest test/integration   # núcleo C++ del firmware
```

Las pruebas E2E son deterministas:
- `MockFaceProvider` con rostros sintéticos (`tests/faces.py`).
- `backend/tests/e2e/esp32_sim.py`: cliente del protocolo firmado del ESP32, sobre `TestClient`.
- Firma HMAC real en peticiones y respuestas.

## Resultados

| Suite | Resultado |
|---|---|
| Backend completo (`pytest`) | **210 aprobadas**: 176 de los módulos, 22 E2E de flujos y 12 de regresión de seguridad |
| Firmware, integración (`test/integration`) | **13 aprobadas**, incluida la comparación de firma con `security.py` del backend |
| Firmware nativo (`pio test -e native`) | 61 aprobadas, según la sesión de firmware; no se repitió aquí |

### Matriz de escenarios pedidos

| Escenario | Prueba (`backend/tests/e2e/test_access_flows.py`) | Resultado esperado y verificado |
|---|---|---|
| Flujo completo (18 pasos) | `test_full_flow_entry_door_close_and_exit` | Registro + rostro + ID `ENG-NNNN` + tarjeta. Sin solicitud se deniega (`NO_VALID_AUTH`): el Registro 1 no concede nada. Tras la solicitud y su aprobación: `AWAITING_FACE → FACE_OK → GRANTED` firmado → abre 5000 ms → cierra. Auditoría en orden (`card_read, awaiting_face, face_ok, granted, entry, door_closed`). `use_count=1`. Segunda pasada = **salida**, con rostro y sin autorización, `access.exit`. Panel con «dentro» y salidas. Cadena de auditoría íntegra |
| Acceso correcto | `test_correct_access_is_fast_and_clean` | Concedido, sin alertas |
| Ingeniero desconocido | `test_unknown_engineer` | Tarjeta sin titular → `CARD_NOT_LINKED`. Persona no registrada con tarjeta válida → `FACE_MISMATCH` |
| RFID desconocido | `test_unknown_rfid` | `UNKNOWN_CARD` + alerta WARN |
| RFID incorrecto | `test_wrong_rfid` | Otra tarjeta del mismo ingeniero (la autorización va ligada a la tarjeta) → `NO_VALID_AUTH`. Tarjeta bloqueada → `CARD_NOT_ACTIVE` |
| Rostro incorrecto | `test_wrong_face`, `test_identical_frames_fail_liveness` | Rostro de un colega → `FACE_MISMATCH`. La misma foto 5 veces → `LIVENESS_FAILED` |
| Ingeniero suspendido | `test_suspended_engineer` | Suspender revoca la solicitud. El intento da `ENGINEER_INACTIVE` + alerta **CRITICAL** |
| Autorización expirada | `test_expired_authorization` | `AUTH_EXPIRED` incluso antes de que el barrido la marque `EXPIRADA`: el motor comprueba la ventana por sí mismo |
| Solicitud pendiente | `test_pending_request` | `REQUEST_PENDING` |
| Autorización revocada | `test_revoked_authorization`, `test_revoked_between_face_and_opening` | `AUTH_REVOKED`, también si se revoca **entre** el rostro y la apertura (paso 14) |
| ESP32 desconectado | `test_esp32_disconnected` | Sin latido > 45 s → `OFFLINE` + `DEVICE_OFFLINE` + evento WS. Vuelve con el siguiente latido. Si el ESP32 no alcanza el backend, la puerta sigue cerrada |
| Sensor sin respuesta | `test_sensor_without_response` | Latido con HC-SR04 en `TIMEOUT` → alerta `SENSOR_FAULT` y estado visible. El acceso **no** se bloquea: `start` con distancia -1 → `AWAITING_FACE` y, con el rostro, `GRANTED` (el sensor está dentro de la sala, protocolo §9) |

### Pruebas adicionales

- `test_inside_sensor_is_not_an_access_factor_and_timeout`: la distancia del HC-SR04 no influye en la decisión (ya no existe `PRESENCE_LOST` en el acceso). Nadie mira a la cámara en 30 s → `TIMEOUT`.
- `test_repeated_failures_lock_the_card`: 3 fallos en 5 min → `REPEATED_FAILURES` CRITICAL y tarjeta bloqueada 10 min (`CARD_LOCKED`).
- `test_device_protocol_rejects_forgery_and_replay`:
  - Firma falsa → 401 firmado + `DEVICE_AUTH_FAIL`.
  - Nonce repetido → `DEVICE_REPLAY`.
  - Reloj desfasado → `DEVICE_CLOCK_SKEW`.
  - Dispositivo desconocido → 401 **sin firma**, que el ESP32 descarta.
  - Un `GRANTED` manipulado no abre la puerta.
- `test_response_signature_matches_firmware_vector`: vector compartido con `firmware/esp32-door/test/test_signing`.
- `test_emergency_close_via_heartbeat`: `EMERGENCY_CLOSE` se entrega una sola vez.
- `test_dashboard_shows_everything`: indicadores, denegaciones por motivo, alertas, dispositivos y últimos intentos.
- `test_websocket_streams_events`, `test_websocket_requires_auth`: eventos en tiempo real y rechazo anónimo (4401).

### Escenarios añadidos (2026-11-15 y 2026-11-17)

Estado al 2026-11-17: `pytest tests/e2e` → **78 aprobadas**; firmware nativo (`pio test -e native`) → **129 aprobadas**;
firmware de integración (`test/integration`) → **13 aprobadas**.

| Escenario | Pruebas | Resultado esperado y verificado |
|---|---|---|
| Intrusión (HC-SR04 dentro de la sala) | `test_intrusion_alarm.py`: `test_someone_inside_with_nobody_authorized_triggers_the_alarm`, `test_no_alarm_while_an_authorized_engineer_is_inside`, `test_alarm_again_after_the_engineer_left`, `test_crossing_the_door_is_not_an_intrusion`, `test_leaving_the_room_never_alarms` | Presencia sin nadie autorizado dentro → `alarm:true` + alerta `INTRUSION` CRITICAL. Sin alarma con un ingeniero dentro ni al cruzar la puerta. Firmware: alarma local sin conexión (`test_controller`) |
| Botón de salida interior | `test_exit_button_and_lcd.py`: `test_button_does_nothing_when_nobody_is_inside`, `test_button_opens_from_inside_without_presence_and_records_exit`, `test_button_with_several_people_inside_opens_without_attribution` | Nadie dentro → `NOBODY_INSIDE`. Una persona dentro → `FACE_OK` → `GRANTED` con «Hasta pronto» y `access.exit`. Firmware: ignorado sin conexión |
| Entrada principal (QR) | `test_entrance_qr.py` (emisión y revocación, orden de denegaciones, límite de 20/min, señal entregada una vez, caducidad a 10 s, respuestas firmadas ligadas al nonce, bitácora QR/RFID), `test_sim_entrance_environment.py` | QR válido con Registro 2 → señal `GRANTED` → LED verde de la entrada y ack. Firmware (`test_entrance`): firma inválida, `id`/`led_ms` erróneos o resultado desconocido ⇒ ignorada; **nunca mueve el servo** |
| DHT11 | `test_environment.py` (histéresis del ventilador y re-armado de alertas, `TEMPERATURA_CRITICA` sin duplicados, `HUMEDAD_FUERA_DE_RANGO`, `SENSOR_DHT_ERROR`, 422 firmado, respuesta sin firma rechazada, consultas `latest` y serie), `test_entrance_qr.py::test_heartbeat_sends_dht_thresholds_and_accepts_dht_sensor` | El backend decide `fan`/`alarm`. Firmware (`test_environment`): 3 fallos ⇒ `ERROR` y ventilador apagado; firma inválida o sin conexión ⇒ respaldo local con los mismos umbrales |

## Verificación en vivo (histórica)

Se hizo con un servidor real, base de datos aislada y la semilla, usando entonces un panel de simulación que
enviaba peticiones HMAC reales al gateway. Ese panel se retiró: el sistema se prueba con el ESP32 físico.

| Paso | Observado |
|---|---|
| Rostros de demostración, y solicitud APROBADA para ENG-0001 | 3 rostros registrados, solicitud vigente |
| Acercarse, tarjeta 04A1B2C3, «Rostro del titular» | `AWAITING_FACE` → `FACE_OK` (similitud 0,97, 5/5) → `GRANTED` firmado → puerta ABIERTA 5 s → cerrada y registrada |
| Segunda pasada | Salida concedida sin rostro (comportamiento anterior a la revisión de seguridad; ahora la salida pide rostro, ver abajo) |
| «Rostro de otro ingeniero» | `FACE_MISMATCH` (0,19, 0/5), la puerta no se abre |
| UID `0BADC0DE` | `UNKNOWN_CARD` |
| HC-SR04 sin respuesta | Alerta `SENSOR_FAULT`. (En esta sesión de 2026-11-14 el firmware aún exigía presencia; desde el 2026-11-15 el sensor está dentro de la sala y la tarjeta se envía igual, protocolo §9) |
| ESP32 desconectado | A los 53 s: `OFFLINE` + alerta `DEVICE_OFFLINE`, visibles en el panel en tiempo real. Al reconectar vuelve a `ONLINE` |
| **Firmware C++ real** (`host_runner`, el núcleo `dcg_core` compilado para PC) contra el gateway real | Respuestas firmadas aceptadas, `GRANTED`, servo a 90°, `OPENED` y `CLOSED:TIMER` confirmados. Auditoría `card_read … entry, door_closed` |
| Páginas Panel, Tarjetas, Accesos, Alertas, Auditoría, Ingenieros, Solicitudes y Kiosco | Cargan con el menú común, sin errores de JavaScript. La verificación de la cadena de auditoría da «Íntegra» |

## Revisión de seguridad de cierre (security-agent)

Revisión en solo lectura del código de F5–F8. Cada hallazgo corregido tiene su prueba en
`backend/tests/e2e/test_security_regressions.py`.

| # | Severidad | Hallazgo | Corrección |
|---|---|---|---|
| A1 | ALTA | Con un solo lector, la «segunda pasada = salida sin rostro» abría la puerta a una tarjeta clonada o prestada usada desde fuera, aunque el titular estuviera suspendido o la tarjeta bloqueada | La salida exige el **1:1 facial** y no una autorización: nadie queda atrapado (un suspendido puede salir con su rostro). Si el titular no está activo, alerta CRITICAL `INACTIVE_ENGINEER`. `biometrics.verify(..., allow_inactive=True)` solo en la salida |
| M1 | MEDIA | El kiosco recibía por WebSocket el UID de tarjeta y otros datos de todas las puertas | Proyección mínima para el kiosco: `id`, `device_code`, `direction`, `state`, `reason` y nombre |
| M2 | MEDIA | `DCG_ENV=prod` aceptaba `DCG_SIMULATION=true` (monta `/sim`, que descifra los secretos reales de los dispositivos) | En producción se rechaza la simulación al arrancar |
| M3 | MEDIA | El token del kiosco viajaba en la URL (logs, historial) y no tenía longitud mínima | Se envía en el primer mensaje del WebSocket. Si llega `?token=`, se guarda y se borra de la URL con `history.replaceState`. `DCG_KIOSK_TOKEN` exige al menos 43 caracteres |
| M4 | MEDIA | Gateway: cuerpo sin límite y una escritura de auditoría por cada petición anónima (DoS) | Cuerpo de 4 KiB como máximo (413). Las peticiones sin dispositivo válido solo se auditan 10 veces por minuto y por IP |
| M5 | MEDIA | Redirección abierta en `?next=` del login (`/\evil`, `/%09/evil`) | Se acepta solo si `new URL(next).origin` es el propio origen |
| B1 | BAJA | El WebSocket seguía abierto tras el logout | La sesión se revalida cada 60 s y se cierra con 4401 |
| B4 | BAJA | Cualquier tarjeta, incluso desconocida, anulaba el intento en curso | Solo lo anula una tarjeta registrada, activa y vinculada (desde el 2026-11-15 ya no se exige presencia: el HC-SR04 está dentro de la sala) |
| B5 | BAJA | Los parámetros de query duplicados podían reordenarse sin invalidar la firma | Se rechazan (`DEVICE_BAD_QUERY`) |
| B6 | BAJA | XSS por el nombre de la cámara USB en el kiosco | `new Option(label, id)` |
| B8 | BAJA | En la auditoría no se distinguían las acciones del kiosco de las del planificador | Actor `system/kiosk` |
| B9 | BAJA | `DCG_SIM_BASE_URL` sin validar | Solo `127.0.0.1`, `localhost` o `::1` |

Aceptados y no corregidos:
- **B2**: `EMERGENCY_CLOSE` se da por entregado al responder el latido. Si se pierde la respuesta, el comando no se repite; basta con volver a pulsarlo.
- **B3**: un `GRANTED` puede repetirse durante 10 s si se pierde la respuesta. El firmware deja de sondear al abrir, así que no da una segunda apertura.
- **B7**: el mensaje de dispositivo desconocido permite enumerar `device_code`, que no son secretos.
- **Rotación del token de kiosco derivado**: para rotarlo hay que definir `DCG_KIOSK_TOKEN`.

## No verificado (limitaciones)

- **Webcam real en el kiosco:** el navegador de pruebas bloquea la cámara. El kiosco se autentica, recibe los eventos
  y la verificación con capturas está probada por API, pero la captura con `getUserMedia` no se ha probado.
- **InsightFace real:** el modelo `buffalo_l` (~300 MB) no está descargado en `data/models`. Toda la verificación se
  hizo con `MockFaceProvider`. Con `DCG_SIMULATION=false` el primer arranque descargará el modelo, y hay que calibrar el umbral con caras reales.
- **ESP32 físico:** el firmware compila para `esp32dev` (según la sesión de firmware), pero no se ha probado en una placa con RC522, HC-SR04 y SG90 reales.
