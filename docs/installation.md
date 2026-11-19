# Instalación de DC Guardian

Tres formas de ejecutarlo: **Docker** (recomendada para la demo), **local** con Python 3.12, y
el **firmware** para el ESP32 físico. El sistema funciona con el hardware real: la placa habla con el
backend por HTTP firmado y el reconocimiento facial usa la webcam del PC.

## 1. Requisitos

| Para | Necesitas |
|---|---|
| Docker | Docker Engine ≥ 24 y el plugin Compose v2 (`docker compose version`) |
| Local | Linux, Python **3.12** (no 3.13/3.14: InsightFace y onnxruntime), `git` |
| Firmware | PlatformIO (CLI o extensión de VS Code), cable USB de datos, ESP32 DevKit v1 |
| Kiosco con webcam | Navegador Chromium o Firefox en el PC con la cámara, abriendo `http://localhost:8000` |

```bash
git clone https://github.com/<usuario>/<repositorio>.git dc-guardian
cd dc-guardian
```

## 2. Docker

### 2.1 Arranque

```bash
cp .env.example .env                 # opcional: puerto, modo y secretos
docker compose build                 # construye la imagen dc-guardian:latest (~1.5 GB)
docker compose up -d                 # arranca; aplica las migraciones al iniciar
docker compose ps                    # STATUS debe pasar a "healthy" (≈ 1 min)
```

Primera vez (datos de demostración y administrador):

```bash
docker compose exec dcguardian python -m scripts.seed
docker compose exec -it dcguardian python -m scripts.create_admin admin --name "Administrador"
```

La semilla imprime **una sola vez** el secreto HMAC del ESP32 `DC-DOOR-01`; cópialo si vas a usar
la placa real. `create_admin` pide la contraseña de forma interactiva.

- Dashboard: <http://localhost:8000> (redirige al login)
- API interactiva (OpenAPI): <http://localhost:8000/docs> (desactivada en `prod`)
- Salud: <http://localhost:8000/api/v1/health>

### 2.2 Operación

| Acción | Comando |
|---|---|
| Ver logs | `docker compose logs -f dcguardian` |
| Detener (conserva los datos) | `docker compose down` |
| Reiniciar | `docker compose restart dcguardian` |
| Reconstruir tras cambiar código o dependencias | `docker compose build --no-cache && docker compose up -d` |
| Shell en el contenedor | `docker compose exec dcguardian sh` |
| Tests dentro de la imagen | no incluidos: la imagen no lleva dependencias de desarrollo (usa la instalación local) |
| **Borrar todos los datos** (BD, claves, modelos) | `docker compose down -v` ⚠ irreversible |

### 2.3 Puertos, volúmenes y variables

| Elemento | Valor |
|---|---|
| Puerto | `8000/tcp` (`DCG_PORT` en `.env` cambia el del host). Publicado en todas las interfaces para que el ESP32 de la LAN llegue al backend |
| Volumen | `dc-guardian-data` → `/data`: `dcguardian.db`, `.dev_keys.json`, `models/` (InsightFace descarga ~300 MB la primera vez que arranca) |
| Red | `dc-guardian-net` (bridge) |
| Usuario | `dcg` (uid 10001), sistema de archivos de solo lectura, `no-new-privileges`, sin capabilities |
| Healthcheck | `GET /api/v1/health` cada 30 s |

Los datos sobreviven a `down`/`up` y a las reconstrucciones de la imagen, porque solo
`down -v` borra el volumen. Copia de seguridad:

```bash
docker run --rm -v dc-guardian-data:/data -v "$PWD":/backup debian:12-slim \
  tar czf /backup/dcg-backup.tgz -C /data dcguardian.db .dev_keys.json
```

Las claves `.dev_keys.json` cifran los secretos de los dispositivos y firman la auditoría.
Sin ellas, la BD restaurada no sirve: guárdalas juntas.

### 2.4 Modos

| Modo | `.env` | Comportamiento |
|---|---|---|
| Desarrollo / demo (por defecto) | `DCG_ENV=dev` | InsightFace real con el kiosco y la webcam, y el ESP32 físico |
| Producción | `DCG_ENV=prod`, `DCG_JWT_SECRET`, `DCG_MASTER_KEY`, `DCG_COOKIE_SECURE=true`, `DCG_FACE_PROVIDER=insightface` (y `DCG_KIOSK_TOKEN` ≥ 43 caracteres si lo defines) | El backend se niega a arrancar si falta algo, o si el proveedor facial es el mock. Requiere HTTPS delante (por ejemplo Nginx o Caddy) |

## 3. Instalación local (sin Docker)

```bash
# 1. Entorno virtual con Python 3.12
python3.12 -m venv backend/.venv
backend/.venv/bin/pip install -r requirements-dev.txt     # o requirements.txt si no vas a ejecutar tests

#    Alternativa reproducible con uv (usa backend/uv.lock):
#    python3 -m venv .tools && .tools/bin/pip install uv && .tools/bin/uv python install 3.12
#    cd backend && ../.tools/bin/uv sync --python 3.12 --extra vision && cd ..

# 2. Configuración
cp backend/.env.example backend/.env

# 3. Base de datos y datos de demostración
cd backend
.venv/bin/alembic upgrade head
.venv/bin/python -m scripts.seed
.venv/bin/python -m scripts.create_admin admin --name "Administrador"

# 4. Backend + frontend (el mismo proceso sirve frontend/)
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
#    con el ESP32 real en la LAN:  --host 0.0.0.0
```

El frontend no necesita compilación ni un servidor aparte: FastAPI lo sirve en `/`.

### Webcam y reconocimiento facial

1. Arranca el backend. La primera vez se
   descarga `buffalo_l` en `data/models` (~300 MB).
2. Registra el rostro: **Ingenieros → ficha → Registrar rostro**. Pide permiso de cámara y
   toma 3–5 muestras con control de calidad.
3. En el PC de la puerta abre **Kiosco**: `http://localhost:8000/pages/kiosk.html?device=DC-DOOR-01`.
   Usa la sesión de administrador o el token de `GET /api/v1/system/kiosk-token`. Con
   `?token=` en la URL, la página lo guarda y lo quita de la barra de direcciones.
4. Cuando una tarjeta válida inicia un intento, el kiosco muestra al titular, captura 5
   fotogramas y los envía a `/vision/verify`.

`getUserMedia` solo funciona en `localhost` o con HTTPS. Si abres el kiosco desde otro equipo
por `http://IP:8000`, el navegador bloqueará la cámara.

### Tests

```bash
cd backend && .venv/bin/pytest                                   # backend
cd firmware/esp32-door && ../../.tools/bin/pio test -e native   # lógica del firmware en el PC
cd firmware/esp32-door && ../../backend/.venv/bin/pytest test/integration   # firmware ↔ gateway real
```

## 4. Firmware ESP32

1. **PlatformIO**: `pipx install platformio` o la extensión *PlatformIO IDE* de VS Code.
   El proyecto usa `platformio/espressif32@6.9.0` (Arduino-ESP32 2.0.x).
   - Con **Arduino IDE** también es posible, pero no está probado. Habría que instalar el core
     ESP32 2.0.x y las librerías MFRC522 1.4.11, ESP32Servo 3.0.6 y ArduinoJson 7.2.1, y copiar
     `lib/dcg_core/src/*` y `src/*` a un único sketch. Se recomienda PlatformIO.
2. **Librerías**: se instalan solas desde `platformio.ini`:
   - `miguelbalboa/MFRC522@1.4.11`
   - `madhephaestus/ESP32Servo@3.0.6`
   - `bblanchon/ArduinoJson@7.2.1`

   El LCD solo usa `Wire`, que viene con el core.
3. **Registrar el dispositivo** en el backend. `scripts.seed` crea `DC-DOOR-01` e imprime su
   secreto. Si lo pierdes, usa **POST `/devices/{id}/rotate-secret`**.
4. **Configurar**:
   ```bash
   cd firmware/esp32-door
   cp include/dcg_config.example.h include/dcg_config.h      # ignorado por git
   ```
   | Macro | Valor |
   |---|---|
   | `DCG_WIFI_SSID` / `DCG_WIFI_PASSWORD` | Tu red WiFi de 2.4 GHz |
   | `DCG_WIFI_SSID_2` / `DCG_WIFI_PASSWORD_2` | Opcional: segunda red de respaldo (se cambia tras 15 s sin conexión). Contraseña `""` = red abierta |
   | `DCG_BACKEND_URL` | `http://<IP-del-PC>:8000`, sin `/` final. Con Docker, el puerto publicado |
   | `DCG_DEVICE_ID` / `DCG_DEVICE_SECRET` | `DC-DOOR-01` y los 64 caracteres hex de la semilla |
   | `DCG_CLOCK_SKEW_S` | Igual que `DCG_DEVICE_CLOCK_SKEW_S` del backend (30) |
   | `DCG_SERVO_*` | Calibración del servo |
   | `DCG_LCD_ENABLED` / `DCG_LCD_I2C_ADDR` | `1` / `0x00` (autodetección) |
5. **Compilar y cargar**:
   ```bash
   pio run -e esp32dev                 # compilar
   pio run -e esp32dev -t upload       # cargar por USB
   pio device monitor                  # consola serie a 115200 baudios
   ```
   En Linux, si el puerto da `Permission denied`: `sudo usermod -aG dialout $USER` y vuelve a
   iniciar sesión.
6. **Verificar los dispositivos** con el firmware de diagnóstico, que no usa la red:
   ```bash
   pio run -e esp32dev-diag -t upload && pio device monitor
   ```
   Comandos: `info` (versión del RC522), `rfid`, `dist`, `servo <0-180>` (con el servo sin
   acoplar), `sweep`, `led`, `buzz`, `button` y `lcd` (escaneo I2C y patrón de prueba). Después
   vuelve a cargar `esp32dev`.
7. **En marcha**: escribe `status` en la consola serie. Debe mostrar `online=1`, `ntp=1` y `lcd=WAIT_CARD`.
   En el panel, la puerta aparece **ONLINE** con distancia y sensores.

Cableado: [cableado.md](cableado.md) · resumen y LCD: [hardware.md](hardware.md).

## 5. Problemas frecuentes

| Síntoma | Causa probable |
|---|---|
| El contenedor no pasa a *healthy* | `docker compose logs dcguardian`: secretos demasiado cortos o vacíos en `.env`, o `prod` sin `DCG_COOKIE_SECURE=true` |
| `DCG_JWT_SECRET must be at least 43 characters` | Hay una variable definida pero vacía en `.env`: coméntala |
| El kiosco dice que la cámara no está disponible | No es `localhost` ni HTTPS, o la cámara está en uso por otra aplicación |
| El ESP32 se queda en `ERROR DE CONEXION` | URL o puerto incorrectos, cortafuegos del PC, reloj sin NTP o secreto distinto |
| `SISTEMA DESCONECTADO` en el LCD | Sin WiFi (el ESP32 solo usa 2.4 GHz) |
| El LCD se enciende pero no muestra texto | Ajusta el contraste con el potenciómetro y comprueba la dirección con `lcd` en el firmware de diagnóstico |
