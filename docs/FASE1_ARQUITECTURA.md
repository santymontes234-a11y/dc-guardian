# DC Guardian — Fase 1: Análisis y Diseño

> Sistema académico de control de acceso inteligente para un Data Center ficticio.
> Estado: **borrador para aprobación**. No se ha implementado código.

---

## 1. Análisis de requisitos

### 1.1 Requisitos funcionales

| ID | Requisito |
|----|-----------|
| RF-01 | Registrar ingenieros (datos personales, foto, embedding facial). El registro **no** concede acceso. |
| RF-02 | Registrar y vincular tarjetas RFID (UID) a un ingeniero. |
| RF-03 | Crear solicitudes de autorización independientes, temporales, vinculadas a ingeniero + tarjeta + área. |
| RF-04 | Administradores aprueban/rechazan/revocan solicitudes; queda registrado quién y cuándo. |
| RF-05 | Expiración automática de solicitudes cuando vence su ventana. |
| RF-06 | Autenticación multifactor en puerta: autorización vigente + RFID + vínculo tarjeta-ingeniero + rostro + ingeniero activo + presencia + validación backend. |
| RF-07 | El servo solo abre tras decisión `GRANTED` firmada por el backend. |
| RF-08 | Auditoría inmutable de todo evento (accesos, cambios administrativos, errores). |
| RF-09 | Alertas por eventos anómalos (tarjeta desconocida, rostro no coincide, intentos repetidos, dispositivo caído, firma inválida). |
| RF-10 | Modo simulación completo sin hardware (ESP32 virtual + rostro simulado). |
| RF-11 | Panel web para administración, monitoreo en tiempo real y kiosco de verificación facial. |

### 1.2 Requisitos no funcionales

- **Seguridad**: principio de mínimo privilegio, *fail-closed* (ante cualquier error, la puerta permanece cerrada), comunicación ESP32↔backend autenticada con HMAC y protección anti-replay.
- **Modularidad**: cada dominio (ingenieros, autorizaciones, acceso, visión, dispositivos, auditoría, alertas) es un módulo con interfaz clara.
- **Escalabilidad**: monolito modular que puede separarse en servicios (p. ej. visión como microservicio) y migrar de SQLite a PostgreSQL vía SQLAlchemy sin reescribir lógica.
- **Trazabilidad**: cada intento de acceso tiene un `correlation_id` que atraviesa ESP32 → backend → visión → auditoría.
- **Privacidad**: embeddings y fotos son datos biométricos; se almacenan localmente, no se exponen por API pública.
- **Rendimiento objetivo**: decisión completa < 5 s tras pasar la tarjeta y mirar a la cámara.

### 1.3 Supuestos

- El backend, la base de datos y la webcam corren en el **mismo PC**; el ESP32 se conecta por WiFi a la misma red local.
- Hay **una puerta / un ESP32** inicialmente, pero el modelo admite varios dispositivos y áreas.
- No hay sensor de puerta (reed switch); el cierre se asume por temporizador del servo.

---

## 2. Arquitectura

### 2.1 Vista general

```
                ┌──────────────────────── PC (red local) ────────────────────────┐
                │                                                                │
 ┌───────────┐  │  ┌──────────────┐  HTTP/WS   ┌──────────────────────────────┐   │
 │ Navegador │◄─┼─►│  Frontend    │◄──────────►│   Backend FastAPI            │   │
 │ (admin /  │  │  │  HTML/CSS/JS │            │  ┌────────────────────────┐  │   │
 │  kiosco)  │  │  └──────────────┘            │  │ engineers  │ requests  │  │   │
 │  webcam   │  │                              │  │ cards      │ access    │  │   │
 └───────────┘  │                              │  │ devices    │ alerts    │  │   │
                │                              │  │ audit      │ auth      │  │   │
                │                              │  └────────────────────────┘  │   │
                │                              │  ┌────────────────────────┐  │   │
                │                              │  │ Vision service         │  │   │
                │                              │  │ OpenCV + InsightFace   │  │   │
                │                              │  │ (provider real / mock) │  │   │
                │                              │  └────────────────────────┘  │   │
                │                              └──────────────┬───────────────┘   │
                │                                             │ SQLAlchemy        │
                │                                      ┌──────▼──────┐            │
                │                                      │   SQLite    │            │
                │                                      └─────────────┘            │
                └───────────────────────────────▲───────────────────────────────┘
                                                │ HTTP + HMAC (WiFi)
                         ┌──────────────────────┴───────────────────┐
                         │ ESP32  ─ RC522 (SPI) ─ HC-SR04 ─ Servo   │
                         │   (o ESP32 simulado en Python)           │
                         └──────────────────────────────────────────┘
```

### 2.2 Decisiones arquitectónicas

| Decisión | Elección | Motivo |
|----------|----------|--------|
| Estilo | Monolito modular FastAPI | Simple de desplegar en un proyecto académico, con fronteras claras para separar después. |
| Captura facial | Navegador (`getUserMedia`) → envía JPEG al backend | Desacopla la cámara del proceso del servidor y sirve igual para registro y kiosco. OpenCV decodifica y preprocesa en backend. |
| Verificación facial | **1:1** (rostro vs. embedding del ingeniero dueño de la tarjeta) | Más seguro y rápido que identificación 1:N; la tarjeta ya indica quién dice ser. |
| Modelo facial | InsightFace `buffalo_l` (ArcFace, 512-d) con fallback `buffalo_s` | Precisión alta; `buffalo_s` si el PC es lento. Ejecución CPU vía onnxruntime. |
| ESP32 ↔ backend | HTTP REST + firma HMAC-SHA256 + timestamp + nonce | Soportado nativamente en ESP32 (HTTPClient + mbedtls), fácil de depurar. MQTT queda como evolución. |
| Decisión al ESP32 | El ESP32 hace *polling* corto (500 ms) del estado de la sesión de acceso | Evita abrir un servidor en el ESP32; respuesta firmada por backend. |
| Tiempo real en UI | WebSocket `/ws/events` | Dashboard, alertas y kiosco se actualizan al instante. |
| Persistencia | SQLAlchemy 2.0 + Alembic sobre SQLite (modo WAL) | Migrable a PostgreSQL. |
| Auth de administradores | Usuario/contraseña (bcrypt) + JWT en cookie HttpOnly | Estándar, suficiente para el alcance. Roles: `admin`, `auditor`. |
| Auditoría | Tabla *append-only* con hash encadenado (SHA-256 del registro anterior) | Permite detectar manipulación del historial. |

### 2.3 Flujo principal de acceso

```
ESP32/HC-SR04   ESP32/RC522        Backend                       Kiosco (webcam)        Servo
     │               │                │                                │                  │
 1. presencia ≤ D cm │                │                                │                  │
     ├──────────────►│ 2. lee UID     │                                │                  │
     │               ├─ POST /device/access/start {uid, distancia} ───►│                  │
     │               │                │ 3. valida: firma, tarjeta,     │                  │
     │               │                │    vínculo, ingeniero activo,  │                  │
     │               │                │    solicitud APROBADA vigente, │                  │
     │               │                │    área = área del dispositivo │                  │
     │               │◄─ {session_id, estado: AWAITING_FACE} ──────────┤                  │
     │               │                ├── WS: "verifique rostro" ─────►│                  │
     │               │                │◄─ POST /vision/verify (frames) ┤ 4. captura N     │
     │               │                │ 5. 1:1 coseno ≥ umbral en k/N  │    frames        │
     │               │                │    frames + liveness básica    │                  │
 6. presencia sigue  │                │                                │                  │
     ├─ GET /device/access/{sid}?dist ►│ 7. presencia aún válida       │                  │
     │               │◄─ {GRANTED, open_ms, firma} ────────────────────┤                  │
     │               ├──────────────────────── 8. abre ────────────────┼─────────────────►│
     │               ├─ POST /device/access/{sid}/opened ─────────────►│ 9. auditoría     │
     │               │                         10. cierra tras open_ms ┼─────────────────►│
```

Cualquier fallo en los pasos 3, 5 o 7 produce `DENIED` con un `reason_code`, se audita y puede generar alerta. La sesión de acceso expira en 30 s (configurable) si no se completa.

### 2.4 Máquina de estados de la sesión de acceso

```
CARD_READ ─► AWAITING_FACE ─► FACE_OK ─► GRANTED ─► OPENED ─► CLOSED
     │              │             │
     └──────────────┴─────────────┴──► DENIED / TIMEOUT
```

### 2.5 Máquina de estados de la solicitud de autorización

```
             aprobar                inicio ventana + uso      fin ventana
PENDIENTE ───────────► APROBADA ─────────────────────────────► FINALIZADA
    │                     │  │
    │ rechazar            │  └── vence sin usarse ──────────► EXPIRADA
    ▼                     └── admin revoca ─────────────────► REVOCADA
RECHAZADA
PENDIENTE ── la ventana termina sin revisión ──────────────► EXPIRADA
```

> Ajuste en F3: una solicitud pendiente expira cuando **termina** su ventana (no cuando empieza),
> para permitir aprobaciones tardías dentro de la ventana. Aprobar fuera de ventana la marca
> `EXPIRADA`. Revocar o finalizar **no** sobrescribe quién aprobó (`reviewed_by`): el cierre se
> guarda aparte en `closed_by` / `closed_at` / `close_notes` (NULL = sistema).
> Suspender o desactivar a un ingeniero, o marcar su tarjeta como `PERDIDA`/`BAJA`, revoca sus
> solicitudes aprobadas y rechaza las pendientes.

- Una solicitud es **vigente** si `estado = APROBADA` y `ahora ∈ [inicio, inicio + duración]`.
- Un *job* periódico (cada 60 s, `asyncio` en el backend) mueve a `EXPIRADA` o `FINALIZADA`.
- Estados terminales: `RECHAZADA`, `EXPIRADA`, `REVOCADA`, `FINALIZADA` (no se reabren; se crea una solicitud nueva).

---

## 3. Modelos de datos (SQLite)

```
admins(id PK, username UQ, password_hash, full_name, role[admin|auditor],
       is_active, token_version, failed_logins, locked_until,
       created_at, last_login_at)

engineers(id PK, engineer_id UQ  -- "ID de ingeniero" generado por el sistema: ENG-0001, ENG-0002…
          full_name, department, position, institutional_email UQ,
          face_embedding_reference UQ NULL  -- UUID opaco hacia la biometría (NULL = sin rostro)
          registration_date, status[ACTIVO|INACTIVO|SUSPENDIDO|ELIMINADO], updated_at)

face_embeddings(id PK, subject_ref FK→engineers.face_embedding_reference ON DELETE CASCADE,
                embedding_encrypted BLOB  -- Fernet(512×float32), clave derivada de DCG_MASTER_KEY
                model_name, quality_score, is_primary, created_at)
   -- 3–5 muestras por ingeniero; sin datos personales ni rutas de imagen
   -- (las fotos se procesan en memoria y se descartan)

rfid_cards(id PK, uid UQ (hex normalizado), engineer_id FK→engineers NULL,
           status[ACTIVA|BLOQUEADA|PERDIDA|BAJA], assigned_at,
           failed_attempts, locked_until)

areas(id PK, code UQ, name, security_level, description)

devices(id PK, device_code UQ, name, area_id FK→areas,
        secret_encrypted  -- cifrado Fernet: el HMAC necesita el secreto en claro, un hash no sirve
       
        presence_threshold_cm, door_open_ms, last_seen_at, status)

authorization_requests(id PK, engineer_id FK, card_id FK→rfid_cards,
        area_id FK, reason, start_at (fecha+hora), duration_minutes,
        end_at (calculado), status[PENDIENTE|APROBADA|RECHAZADA|EXPIRADA|
        REVOCADA|FINALIZADA], reviewed_by FK→admins NULL, reviewed_at,
        review_notes, created_at, first_used_at, use_count)
   -- CHECK: la tarjeta debe pertenecer al ingeniero (validado en servicio)

access_sessions(id PK uuid, device_id FK, direction[ENTRADA|SALIDA], card_uid_raw, card_id FK NULL,
        engineer_id FK NULL, request_id FK NULL, state, reason_code,
        face_score, presence_cm_start, presence_cm_final,
        created_at, decided_at, opened_at, closed_at)

alerts(id PK, type, severity[INFO|WARN|CRITICAL], message, device_id NULL,
       engineer_id NULL, session_id NULL, created_at,
       acknowledged_by NULL, acknowledged_at NULL)

audit_log(id PK, ts, actor_type[admin|device|system|engineer], actor_id,
          action, entity, entity_id, details_json, correlation_id,
          prev_hash, hash)

device_nonces(device_id, nonce, ts)  -- anti-replay, purga > 5 min
```

> Ajuste en el módulo de Registro 1: columnas renombradas según la especificación del módulo
> (migración 0004). `ELIMINADO` = datos personales y biométricos borrados (derecho de supresión);
> la fila conserva solo el `engineer_id`, que nunca se reutiliza, para no romper la auditoría.

**Separación de los dos registros** (regla fundamental): `engineers` + `face_embeddings` es el Registro 1; `authorization_requests` es el Registro 2. No existe ningún campo en `engineers` que otorgue acceso; el motor de acceso **solo** consulta `authorization_requests` vigentes.

---

## 4. API REST (prefijo `/api/v1`)

### 4.1 Administración (JWT, rol `admin` salvo indicación)

| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/auth/login` · `/auth/logout` · GET `/auth/me` | Sesión de administrador |
| GET/POST | `/engineers` | Listar / crear ingeniero |
| GET/PATCH | `/engineers/{id}` | Detalle / editar (incluye cambio de estado) |
| POST | `/engineers/{id}/face` | Registrar muestras faciales (imágenes) → embeddings |
| DELETE | `/engineers/{id}/face/{emb_id}` | Eliminar muestra |
| GET/POST | `/cards` | Listar / registrar tarjeta |
| PATCH | `/cards/{id}` | Vincular a ingeniero, bloquear, dar de baja |
| GET/POST | `/areas` · `/devices` | Catálogos (POST `/devices` devuelve el secreto **una sola vez**) |
| GET/POST | `/requests` | Listar (filtros por estado) / crear solicitud |
| POST | `/requests/{id}/approve` · `/reject` · `/revoke` · `/finalize` | Transiciones de estado |
| GET | `/access-sessions` | Historial de intentos (rol `auditor` también) |
| GET | `/alerts` · POST `/alerts/{id}/ack` | Alertas |
| GET | `/audit` · GET `/audit/verify` | Log de auditoría / verificar cadena de hashes |
| GET | `/stats/dashboard` | Métricas para el panel |

### 4.2 Dispositivo (HMAC, sin JWT)

| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/device/heartbeat` | Latido cada 15 s (estado, RSSI, distancia actual) |
| POST | `/device/presence` | Cambio de presencia (entra/sale del umbral) |
| POST | `/device/access/start` | `{uid, distance_cm}` → crea sesión de acceso |
| GET | `/device/access/{session_id}?distance_cm=` | Polling de decisión |
| POST | `/device/access/{session_id}/opened` · `/closed` | Confirmación de actuación del servo |

### 4.3 Visión / kiosco

| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/vision/verify` | `{session_id, frames[]}` → verificación 1:1 (token de kiosco) |
| POST | `/vision/quality` | Evalúa una imagen (rostro único, nitidez, tamaño) antes de registrar |

### 4.4 Tiempo real y simulación

| Método | Ruta | Descripción |
|--------|------|-------------|
| WS | `/ws/events` | Eventos: `access.*`, `alert.created`, `device.status`, `request.updated` |
| POST | `/sim/...` | Solo con `DCG_SIMULATION=true`: controlar ESP32 virtual |

Errores con formato uniforme: `{"error": {"code": "CARD_NOT_LINKED", "message": "...", "correlation_id": "..."}}`.

---

## 5. Comunicación ESP32 ↔ Backend

### 5.1 Firma de mensajes

Cabeceras en cada petición del dispositivo:

```
X-Device-Id:   DC-DOOR-01
X-Timestamp:   1763130000          (epoch s, tolerancia ±30 s; hora vía NTP)
X-Nonce:       9f2c...             (aleatorio 16 bytes, único por petición)
X-Signature:   hex(HMAC_SHA256(secret, method + "\n" + path + "\n" +
                                       canonical_query + "\n" +
                                       timestamp + "\n" + nonce + "\n" +
                                       sha256(body)))
```

`canonical_query` = parámetros de la query ordenados y codificados (`k=v&k2=v2`, vacío si no hay).
La query también se firma porque transporta datos de decisión (`distance_cm`).

El backend rechaza firma inválida, timestamp fuera de ventana o nonce repetido → alerta `DEVICE_AUTH_FAIL`. Las respuestas de decisión (`GRANTED`) también van firmadas por el backend para que el ESP32 no acepte respuestas falsificadas.

### 5.2 Ejemplo

```json
POST /api/v1/device/access/start
{ "uid": "04A1B2C3", "distance_cm": 32.5, "fw": "1.0.0" }

200 { "session_id": "b6e1...", "state": "AWAITING_FACE", "poll_ms": 500, "timeout_s": 30 }

GET /api/v1/device/access/b6e1...?distance_cm=30.1
200 { "state": "GRANTED", "open_ms": 5000, "sig": "..." }
200 { "state": "DENIED", "reason_code": "FACE_MISMATCH" }
```

### 5.3 Firmware ESP32 (PlatformIO + Arduino)

Máquina de estados: `IDLE → PRESENCE → CARD_READ → WAITING_DECISION → DOOR_OPEN → DOOR_CLOSING → IDLE` (+ `ERROR`/`OFFLINE` → puerta cerrada).

Conexión sugerida:

| Componente | Pin ESP32 | Nota |
|------------|-----------|------|
| RC522 SDA/SS | GPIO 5 | SPI VSPI; **alimentar a 3.3 V** |
| RC522 SCK / MOSI / MISO | GPIO 18 / 23 / 19 | |
| RC522 RST | GPIO 22 | |
| HC-SR04 TRIG | GPIO 26 | |
| HC-SR04 ECHO | GPIO 27 | **Divisor de tensión 5 V→3.3 V** (p. ej. 1 kΩ / 2 kΩ) |
| Servo SG90 señal | GPIO 13 | SG90 (9 g) alimentado a 5 V desde pin VIN/5V (USB) con condensador 470 µF; fuente externa 5 V recomendada si hay reinicios; GND común |
| LED verde / rojo, buzzer | GPIO 25 / 33 / 32 | Retroalimentación al usuario (opcional) |

Librerías: `MFRC522`, `ESP32Servo`, `ArduinoJson`, `HTTPClient`, `mbedtls/md.h` (HMAC), `time.h` (NTP). Configuración (WiFi, URL, secreto) en `include/dcg_config.h` excluido de git (`dcg_config.example.h` versionado; no se llama `config.h` porque el SDK del ESP32 ya trae uno). HC-SR04: mediana de 5 lecturas para filtrar ruido.

---

## 6. Servicio de reconocimiento facial

- **Interfaz** `FaceProvider` con dos implementaciones: `InsightFaceProvider` (real) y `MockFaceProvider` (simulación: decide por parámetro).
- **Registro**: 3–5 fotos → detección (exactamente 1 rostro, tamaño mínimo, nitidez Laplaciano) → embedding normalizado L2 → `face_embeddings`.
- **Verificación**: N = 5 frames; aceptar si ≥ k = 3 tienen similitud coseno ≥ umbral (inicial **0.45**, calibrable) contra el mejor embedding del ingeniero.
- **Liveness básica** (académica): variación de pose/posición del rostro entre frames y rechazo de frames idénticos; documentar que no protege contra ataques avanzados.
- El modelo se carga **una vez** al arrancar (lazy singleton) para evitar latencia por petición.

---

## 7. Auditoría, alertas y simulación

**Auditoría**: toda acción relevante → `audit_log` con hash encadenado; endpoint de verificación recalcula la cadena.

**Alertas** (reglas iniciales):

| Tipo | Disparador | Severidad |
|------|-----------|-----------|
| `UNKNOWN_CARD` | UID no registrado | WARN |
| `CARD_NOT_LINKED` / `NO_VALID_AUTH` | tarjeta sin vínculo o sin solicitud vigente | WARN |
| `FACE_MISMATCH` | rostro no coincide | WARN |
| `REPEATED_FAILURES` | ≥ 3 fallos en 5 min misma tarjeta → bloqueo temporal 10 min | CRITICAL |
| `INACTIVE_ENGINEER` | ingeniero inactivo/suspendido intenta acceder | CRITICAL |
| `DEVICE_AUTH_FAIL` | firma/nonce/timestamp inválido | CRITICAL |
| `DEVICE_OFFLINE` | sin heartbeat > 45 s | WARN |
| `PRESENCE_LOST` | persona se aleja antes de la decisión | INFO |

**Simulación** (`DCG_SIMULATION=true`):
- `simulator/esp32_sim.py`: cliente que implementa el mismo protocolo firmado (útil también como test de integración).
- Panel web "Simulador": botones para acercar persona (distancia), pasar tarjeta (selector de UID), forzar resultado facial o usar la webcam real, y servo virtual animado.
- Datos semilla (`seed.py`): áreas, dispositivo, ingenieros y tarjetas de prueba.

---

## 8. Estructura de carpetas

```
dc-guardian/
├── .claude/
│   └── agents/                     # definiciones de subagentes
│       ├── hardware-agent.md
│       ├── vision-agent.md
│       ├── database-agent.md
│       ├── backend-agent.md
│       ├── frontend-agent.md
│       ├── security-agent.md
│       └── integration-agent.md
├── CLAUDE.md                       # convenciones del proyecto
├── README.md
├── docs/
│   ├── FASE1_ARQUITECTURA.md
│   ├── api.md  · protocolo-esp32.md · cableado.md · amenazas.md
├── backend/
│   ├── pyproject.toml
│   ├── .env.example
│   ├── app/
│   │   ├── main.py                 # crea app, monta routers, static, WS
│   │   ├── core/                   # config, security (JWT, HMAC), logging, errors
│   │   ├── db/                     # session, base, migrations (alembic)
│   │   ├── models/                 # SQLAlchemy
│   │   ├── schemas/                # Pydantic
│   │   ├── repositories/           # acceso a datos
│   │   ├── services/
│   │   │   ├── engineers.py · cards.py · requests.py
│   │   │   ├── access_engine.py    # orquesta la decisión multifactor
│   │   │   ├── audit.py · alerts.py · scheduler.py
│   │   ├── vision/
│   │   │   ├── provider.py         # interfaz FaceProvider
│   │   │   ├── insightface_provider.py · mock_provider.py
│   │   │   └── quality.py · liveness.py
│   │   ├── api/v1/                 # routers: auth, engineers, cards, requests,
│   │   │                           # devices, device_gateway, vision, audit, alerts, sim
│   │   └── ws/                     # hub de eventos
│   ├── scripts/seed.py · create_admin.py
│   └── tests/                      # unit + integración (pytest)
├── frontend/
│   ├── index.html                  # login
│   ├── pages/ dashboard · engineers · requests · cards · access-log
│   │          alerts · audit · simulator · kiosk
│   ├── css/  (tokens, layout, componentes)
│   └── js/   api.js · ws.js · auth.js · camera.js · pages/*.js
├── firmware/
│   └── esp32-door/  platformio.ini · src/main.cpp · src/*.h · include/dcg_config.example.h
├── simulator/
│   └── esp32_sim.py
└── data/                           # (gitignored) db.sqlite, fotos, modelos
```

---

## 9. Subagentes y responsabilidades

Cada subagente tendrá un archivo en `.claude/agents/` con su ámbito, archivos que le pertenecen y criterios de "terminado". Regla: **un agente no edita archivos de otro sin pasar por `integration-agent`**.

| Agente | Responsabilidad | Archivos propios | Entregable |
|--------|-----------------|------------------|------------|
| **database-agent** | Modelos SQLAlchemy, migraciones Alembic, repositorios, datos semilla, índices | `backend/app/models`, `db`, `repositories`, `scripts/seed.py` | Esquema migrable + tests de repositorio |
| **backend-agent** | Routers, schemas, servicios de dominio, motor de acceso, scheduler, WebSocket, alertas | `backend/app/api`, `schemas`, `services`, `ws`, `main.py` | API documentada (OpenAPI) + tests |
| **vision-agent** | Providers InsightFace/mock, calidad de imagen, liveness, calibración de umbral | `backend/app/vision` | Registro y verificación 1:1 con métricas |
| **hardware-agent** | Firmware ESP32, cableado, cliente HMAC en C++, simulador Python del ESP32 | `firmware/`, `simulator/`, `docs/cableado.md` | Firmware compilable + simulador compatible |
| **frontend-agent** | Páginas HTML/CSS/JS, kiosco con webcam, dashboard en tiempo real, simulador visual | `frontend/` | UI funcional contra la API |
| **security-agent** | Modelo de amenazas, JWT, HMAC/anti-replay, hash de auditoría, revisión de cada fase | `backend/app/core/security.py`, `docs/amenazas.md` | Revisión y hallazgos por fase |
| **integration-agent** | Contratos entre módulos, pruebas end-to-end (simulador → backend → visión → UI), README, coordinación | `backend/tests/e2e`, `README.md`, `CLAUDE.md`, `docs/api.md` | Demo completa reproducible |

---

## 10. Riesgos identificados

| # | Riesgo | Impacto | Mitigación |
|---|--------|---------|------------|
| R1 | **Python 3.14** del sistema: InsightFace/onnxruntime pueden no tener *wheels* compatibles | Alto | Usar entorno virtual con **Python 3.11 o 3.12** (`uv` o `pyenv`); verificar instalación en la Fase 2 antes de nada. |
| R2 | InsightFace requiere compilador C++ y descarga de modelos (~300 MB) | Medio | Documentar dependencias (`build-essential`), cachear modelos en `data/models`, provider mock para seguir trabajando. |
| R3 | Suplantación con foto/pantalla | Medio | Liveness básica + multi-frame; declarar limitación en el informe. |
| R4 | Echo del HC-SR04 a 5 V daña el ESP32 | Alto (hardware) | Divisor de tensión obligatorio. |
| R5 | Picos de corriente del SG90 (hasta ~650 mA en bloqueo) provocan caídas de tensión / reinicios del ESP32 | Medio | Alimentar desde 5 V (nunca 3.3 V), condensador 470 µF junto al servo, GND común; fuente externa si hay reinicios. Limitar el ángulo (0°–90°) para no forzar el tope mecánico. |
| R6 | Clonación de tarjetas MIFARE Classic (UID copiable) | Medio | Por diseño el UID nunca basta: se exige rostro + autorización. Documentarlo. |
| R7 | Replay o suplantación del ESP32 en la red | Alto | HMAC + nonce + timestamp + respuesta firmada; HTTPS opcional. |
| R8 | Desincronización horaria del ESP32 | Medio | NTP al arrancar; si falla, el dispositivo no opera (fail-closed). |
| R9 | Falsos rechazos por iluminación/cámara | Medio | Calibrar umbral con datos reales, varias muestras por ingeniero, guía visual en kiosco. |
| R10 | Concurrencia en SQLite | Bajo | Modo WAL, transacciones cortas; un único proceso backend. |
| R11 | Datos biométricos (privacidad) | Medio | Solo local, carpeta `data/` fuera de git, endpoint de borrado de muestras. |
| R12 | Alcance amplio para un parcial | Alto | Plan incremental con demo funcional desde el modo simulación. |

---

## 11. Plan de desarrollo

| Fase | Contenido | Agentes | Criterio de salida |
|------|-----------|---------|--------------------|
| **F1** | Este documento | — | Aprobación del usuario |
| **F2 – Base** | Estructura, entorno Python 3.11/3.12, `pyproject`, config, modelos + migraciones, seed, auth de admins, definiciones de `.claude/agents` | database, backend, security | `pytest` pasa; login funciona |
| **F3 – Dominio** | CRUD ingenieros, tarjetas, áreas, dispositivos; solicitudes con máquina de estados y scheduler; auditoría encadenada | backend, database, security | Tests de transiciones y auditoría |
| **F4 – Visión** | Providers mock/real, registro facial, verificación 1:1, calibración | vision | Verificación < 2 s en CPU |
| **F5 – Motor de acceso + gateway** | Endpoints de dispositivo con HMAC, sesiones de acceso, alertas, simulador Python | backend, security, hardware | Flujo completo en simulación (E2E) |
| **F6 – Frontend** | Login, dashboard WS, gestión, kiosco con webcam, panel simulador | frontend | Demo navegable de extremo a extremo |
| **F7 – Firmware** | ESP32 con RC522, HC-SR04, servo, HMAC, NTP | hardware | Firmware compila; prueba con hardware real |
| **F8 – Integración y cierre** | Pruebas E2E, revisión de seguridad, README, guía de demo | integration, security | Demo reproducible + documentación |

Cada fase termina con una revisión del `security-agent` y una pausa para tu validación.

---

## 12. Decisiones pendientes (necesito tu confirmación)

1. **Uso de la autorización**: ¿permite **múltiples entradas** dentro de la ventana (propuesto) o es de **un solo uso**?
2. **¿Quién crea las solicitudes?** Propuesto: el administrador las registra en nombre del ingeniero (no hay portal de ingenieros). Alternativa: portal para que el ingeniero las solicite.
3. **Kiosco facial**: ¿la webcam está junto a la puerta (kiosco en navegador del PC)? Propuesto: sí.
4. **Salida**: ¿se registra la salida (p. ej. botón o segunda pasada de tarjeta) para cerrar la solicitud como `FINALIZADA`? Propuesto: segunda pasada de tarjeta = salida, sin rostro.
5. ~~**Servo**: ¿SG90 o MG996R?~~ **Resuelto: micro servo SG90 (9 g).** PWM 50 Hz, pulso 500–2400 µs con `ESP32Servo`; cerrado = 0°, abierto = 90°.
6. **Idioma de la UI y del código**: propuesto UI en español, código/identificadores en inglés.

---

## 13. Ampliaciones posteriores al diseño aprobado

> Nota añadida tras la implementación. El diseño de las secciones anteriores no se ha reescrito;
> donde haya diferencias, mandan los documentos enlazados aquí.

| Fecha | Cambio | Contrato |
|-------|--------|----------|
| 2026-11-15 | El **HC-SR04** pasa a estar **dentro de la sala** como alarma de intrusión (`POST /device/presence` → alerta `INTRUSION`) y deja de ser factor de acceso (`PRESENCE_LOST` y `SENSOR_ERROR` ya no deniegan). El **pulsador del GPIO 4** pasa a ser **botón de salida** (`POST /device/exit-button`), no cierre de emergencia | [protocolo-esp32.md §8–§9](protocolo-esp32.md) |
| 2026-11-17 | Escenario **Telecom Conecta** (Proyecto Parcial 3): áreas `ENTRADA_PRINCIPAL` y `SALA_SERVIDORES`; roles *Administrador de TI*, *Ingeniero de red*, *Personal de limpieza* y *Proveedor*. **Acceso por QR** en la entrada principal (LED verde, GPIO 14), **DHT11** en la sala (GPIO 16) con ventilador (GPIO 2) y **bitácora** por zona y método (`GET /api/v1/access-log`). Tablas nuevas `qr_credentials`, `entrance_events` y `environment_readings` (migración 0006) | [contrato-qr-dht11.md](contrato-qr-dht11.md) · [protocolo-esp32.md §10–§11](protocolo-esp32.md) · [api.md](api.md) |

La regla fundamental no cambia: el QR, igual que la tarjeta, **solo identifica**; la entrada
principal también exige una solicitud `APROBADA` y vigente del Registro 2.
