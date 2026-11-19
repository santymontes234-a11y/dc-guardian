#!/usr/bin/env bash
# DC Guardian — arranque local completo con un solo comando.
#
#   ./run.sh                 arranca el sistema en http://127.0.0.1:8000
#   ./run.sh --help          todas las opciones
#
# Qué hace, en orden (lo mismo que README § 8, automatizado):
#   1. Comprueba el entorno virtual de Python 3.12 (backend/.venv); lo crea si no existe.
#   2. Instala dependencias de requirements.txt solo si falta alguna.
#   3. Aplica migraciones pendientes (alembic upgrade head).
#   4. Carga los datos de demostración solo si la base de datos está vacía (scripts.seed).
#   5. Si no hay ningún administrador, ofrece crearlo (scripts.create_admin).
#   6. Arranca el backend (uvicorn), que sirve también el frontend y el ESP32 virtual,
#      y espera a que /api/v1/health responda.
# Ctrl+C detiene todo. Una segunda ejecución simultánea se rechaza.

set -Eeuo pipefail

# ------------------------------------------------------------------ rutas (relativas al script)
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
VENV_DIR="$BACKEND_DIR/.venv"
PY="$VENV_DIR/bin/python"
REQUIREMENTS="$ROOT_DIR/requirements.txt"
ENV_FILE="$BACKEND_DIR/.env"
DATA_DIR="${DCG_DATA_DIR:-$ROOT_DIR/data}"
LOCK_FILE="$DATA_DIR/.run.lock"
UV="$ROOT_DIR/.tools/bin/uv"

# ------------------------------------------------------------------ opciones
HOST="127.0.0.1"
PORT="8000"
RELOAD=""
SKIP_INSTALL=0

usage() {
  cat <<EOF
Uso: ./run.sh [opciones]

  --port N        Puerto HTTP (por defecto 8000)
  --host H        Interfaz de escucha (por defecto 127.0.0.1)
  --lan           Escuchar en 0.0.0.0 para que el ESP32 físico de la LAN llegue al backend
  --reload        Recargar el backend al cambiar el código (desarrollo)
  --no-install    No instalar dependencias aunque falten
  -h, --help      Mostrar esta ayuda
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)       PORT="${2:?--port necesita un valor}"; shift 2 ;;
    --host)       HOST="${2:?--host necesita un valor}"; shift 2 ;;
    --lan)        HOST="0.0.0.0"; shift ;;
    --reload)     RELOAD="--reload"; shift ;;
    --no-install) SKIP_INSTALL=1; shift ;;
    -h|--help)    usage; exit 0 ;;
    *) echo "Opción desconocida: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if ! [[ "$PORT" =~ ^[0-9]+$ ]] || (( PORT < 1 || PORT > 65535 )); then
  echo "Puerto inválido: $PORT" >&2; exit 2
fi

# ------------------------------------------------------------------ salida
if [[ -t 1 ]]; then
  C_STEP=$'\e[1;36m'; C_OK=$'\e[1;32m'; C_WARN=$'\e[1;33m'; C_ERR=$'\e[1;31m'; C_OFF=$'\e[0m'
else
  C_STEP=""; C_OK=""; C_WARN=""; C_ERR=""; C_OFF=""
fi
step() { printf '%s==>%s %s\n' "$C_STEP" "$C_OFF" "$*"; }
ok()   { printf '%s  ✔%s %s\n' "$C_OK" "$C_OFF" "$*"; }
warn() { printf '%s  !%s %s\n' "$C_WARN" "$C_OFF" "$*" >&2; }
die()  { printf '%s  ✘ Error:%s %s\n' "$C_ERR" "$C_OFF" "$*" >&2; exit 1; }

# ------------------------------------------------------------------ limpieza de procesos
SERVER_PID=""
cleanup() {
  local code=$?
  trap - EXIT INT TERM
  if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    step "Deteniendo el backend (PID $SERVER_PID)…"
    # uvicorn corre en su propio grupo de procesos (setsid): se detiene el grupo entero,
    # así no quedan vivos ni el recargador ni sus hijos.
    kill -TERM -- "-$SERVER_PID" 2>/dev/null || kill -TERM "$SERVER_PID" 2>/dev/null || true
    for _ in $(seq 1 50); do
      kill -0 "$SERVER_PID" 2>/dev/null || break
      sleep 0.2
    done
    if kill -0 "$SERVER_PID" 2>/dev/null; then
      warn "El backend no se detuvo en 10 s; forzando la salida."
      kill -KILL -- "-$SERVER_PID" 2>/dev/null || kill -KILL "$SERVER_PID" 2>/dev/null || true
    fi
    wait "$SERVER_PID" 2>/dev/null || true
    ok "Backend detenido."
  fi
  exit "$code"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'warn "Falló el comando en la línea $LINENO."' ERR

cd "$ROOT_DIR"
[[ -d "$BACKEND_DIR/app" && -f "$REQUIREMENTS" ]] \
  || die "No se encuentra backend/app o requirements.txt junto a run.sh."

# ------------------------------------------------------------------ una sola instancia
mkdir -p "$DATA_DIR"
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK_FILE"
  flock -n 9 || die "DC Guardian ya se está ejecutando desde este proyecto (bloqueo $LOCK_FILE).
     Detén la otra instancia con Ctrl+C antes de iniciar una nueva."
else
  warn "flock no está disponible: no se puede impedir una segunda instancia (solo se comprueba el puerto)."
fi

# ------------------------------------------------------------------ 1. entorno virtual
step "Comprobando el entorno virtual de Python 3.12 (backend/.venv)…"
if [[ ! -x "$PY" ]]; then
  warn "No existe backend/.venv; se creará con Python 3.12."
  if command -v python3.12 >/dev/null 2>&1; then
    python3.12 -m venv "$VENV_DIR"
  elif [[ -x "$UV" ]]; then
    "$UV" venv --python 3.12 "$VENV_DIR"
  else
    die "Hace falta Python 3.12 (python3.12) o uv en .tools/bin/uv para crear el entorno virtual."
  fi
fi
PY_VERSION="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
[[ "$PY_VERSION" == "3.12" ]] \
  || die "backend/.venv usa Python $PY_VERSION; el proyecto necesita 3.12 (InsightFace/onnxruntime)."
# Equivalente a 'source backend/.venv/bin/activate' para este script y sus procesos hijos.
export VIRTUAL_ENV="$VENV_DIR"
export PATH="$VENV_DIR/bin:$PATH"
ok "Python $PY_VERSION en backend/.venv"

# ------------------------------------------------------------------ 2. dependencias
step "Comprobando dependencias de requirements.txt…"
# Devuelve los paquetes declarados que no están instalados; avisa de versiones distintas.
MISSING="$("$PY" - "$REQUIREMENTS" <<'PYEOF'
import re, sys, importlib.metadata as md
missing = []
for raw in open(sys.argv[1], encoding="utf-8"):
    line = raw.split("#", 1)[0].strip()
    if not line or line.startswith("-"):
        continue
    m = re.match(r"([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?\s*(?:==\s*(\S+))?", line)
    if not m:
        continue
    name, pinned = m.group(1), m.group(2)
    try:
        installed = md.version(name)
    except md.PackageNotFoundError:
        missing.append(name)
        continue
    if pinned and installed != pinned:
        print(f"aviso: {name} {installed} instalado (requirements.txt fija {pinned})", file=sys.stderr)
print(" ".join(missing))
PYEOF
)"
if [[ -z "$MISSING" ]]; then
  ok "Todas las dependencias están instaladas."
elif (( SKIP_INSTALL )); then
  die "Faltan dependencias ($MISSING) y se indicó --no-install."
else
  warn "Faltan: $MISSING. Instalando desde requirements.txt…"
  if "$PY" -m pip --version >/dev/null 2>&1; then
    "$PY" -m pip install -r "$REQUIREMENTS" || die "pip no pudo instalar las dependencias."
  elif [[ -x "$UV" ]]; then
    "$UV" pip install --python "$PY" -r "$REQUIREMENTS" || die "uv no pudo instalar las dependencias."
  else
    die "El entorno no tiene pip y no se encontró .tools/bin/uv para instalar dependencias."
  fi
  ok "Dependencias instaladas."
fi

# ------------------------------------------------------------------ configuración
env_file_defines() {  # ¿backend/.env define la variable $1?
  [[ -f "$ENV_FILE" ]] && grep -Eq "^[[:space:]]*(export[[:space:]]+)?$1[[:space:]]*=" "$ENV_FILE"
}
[[ -f "$ENV_FILE" ]] || warn "No existe backend/.env: se usan los valores por defecto (ver backend/.env.example)."

# Validar la configuración ahora da un mensaje claro en vez de un traceback de uvicorn.
cd "$BACKEND_DIR"
CONFIG_ERR="$(mktemp)"
if ! SETTINGS_OUT="$("$PY" -c 'from app.core.config import get_settings as g; s=g(); print(s.env)' 2>"$CONFIG_ERR")"; then
  DETAIL="$(grep -v -E '^(Traceback|  File |    )' "$CONFIG_ERR" | tail -n 8)"
  rm -f "$CONFIG_ERR"
  die "Configuración inválida (revisa backend/.env y las variables DCG_*):
$DETAIL"
fi
rm -f "$CONFIG_ERR"
DCG_ENV_EFFECTIVE="$SETTINGS_OUT"
ok "Entorno: $DCG_ENV_EFFECTIVE"

# ------------------------------------------------------------------ puerto libre
port_in_use() {
  "$PY" - "$1" <<'PYEOF'
import socket, sys
s = socket.socket()
s.settimeout(0.5)
sys.exit(0 if s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
PYEOF
}
if port_in_use "$PORT"; then
  die "El puerto $PORT ya está en uso por otro proceso. Libéralo o usa ./run.sh --port <otro>."
fi

# ------------------------------------------------------------------ 3. migraciones
step "Aplicando migraciones de la base de datos (alembic upgrade head)…"
"$VENV_DIR/bin/alembic" upgrade head || die "Las migraciones fallaron; la base de datos no se ha modificado más allá del último paso válido."
ok "Esquema al día."

# ------------------------------------------------------------------ 4. datos de demostración
db_count() {  # número de filas del modelo $1 (Device, Admin, …)
  "$PY" -c "
import logging; logging.disable(logging.CRITICAL)
from sqlalchemy import func, select
from app.db.session import SessionLocal
from app.models import $1
with SessionLocal() as db:
    print(db.execute(select(func.count()).select_from($1)).scalar_one())"
}
step "Comprobando los datos de demostración…"
DEVICES="$(db_count Device)" || die "No se pudo consultar la base de datos."
if [[ "$DEVICES" == "0" ]]; then
  warn "Base de datos vacía: cargando datos de demostración (scripts.seed)."
  "$PY" -m scripts.seed || die "La carga de datos de demostración falló."
  warn "Guarda el secreto HMAC mostrado arriba si vas a usar el ESP32 físico: no se vuelve a mostrar."
else
  ok "Datos ya cargados ($DEVICES dispositivo(s)); no se repite la semilla."
fi

# ------------------------------------------------------------------ 5. administrador
ADMINS="$(db_count Admin)" || die "No se pudo consultar la base de datos."
if [[ "$ADMINS" == "0" ]]; then
  if [[ -t 0 && -t 1 ]]; then
    warn "No hay ningún administrador: sin él no se puede iniciar sesión en la web."
    read -r -p "    ¿Crear uno ahora? [S/n] " answer
    if [[ ! "$answer" =~ ^[nN] ]]; then
      read -r -p "    Usuario [admin]: " admin_user
      admin_user="${admin_user:-admin}"
      "$PY" -m scripts.create_admin "$admin_user" --name "Administrador" \
        || warn "No se creó el administrador; puedes hacerlo luego con: cd backend && .venv/bin/python -m scripts.create_admin admin"
    fi
  else
    warn "No hay ningún administrador. Créalo con: cd backend && .venv/bin/python -m scripts.create_admin admin"
  fi
else
  ok "$ADMINS administrador(es) registrado(s)."
fi

# ------------------------------------------------------------------ 6. backend + frontend
step "Iniciando el backend FastAPI (sirve también el frontend y el ESP32 virtual) en $HOST:$PORT…"
# setsid: grupo de procesos propio, para que cleanup() pueda detenerlo entero.
setsid "$VENV_DIR/bin/uvicorn" app.main:app --host "$HOST" --port "$PORT" $RELOAD &
SERVER_PID=$!

HEALTH_URL="http://127.0.0.1:$PORT/api/v1/health"
health_ok() {
  "$PY" - "$HEALTH_URL" <<'PYEOF'
import json, sys, urllib.request
try:
    with urllib.request.urlopen(sys.argv[1], timeout=2) as r:
        sys.exit(0 if json.load(r).get("status") == "ok" else 1)
except Exception:
    sys.exit(1)
PYEOF
}
READY=0
for _ in $(seq 1 120); do          # hasta 60 s
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    wait "$SERVER_PID" 2>/dev/null && rc=0 || rc=$?
    SERVER_PID=""
    die "El backend terminó durante el arranque (código $rc). Revisa los mensajes anteriores."
  fi
  if health_ok; then READY=1; break; fi
  sleep 0.5
done
(( READY )) || die "El backend no respondió en $HEALTH_URL tras 60 s."

DISPLAY_HOST="$HOST"
[[ "$HOST" == "0.0.0.0" || "$HOST" == "127.0.0.1" ]] && DISPLAY_HOST="localhost"
BASE="http://$DISPLAY_HOST:$PORT"
echo
ok "DC Guardian está en marcha (PID $SERVER_PID)."
cat <<EOF
     Aplicación web   $BASE
     Entrada QR       $BASE/pages/entrance.html
     Kiosco facial    $BASE/pages/kiosk.html?device=DC-DOOR-01
     Salud            $HEALTH_URL
EOF
[[ "$DCG_ENV_EFFECTIVE" != "prod" ]] && echo "     API (OpenAPI)    $BASE/docs"
[[ "$HOST" == "0.0.0.0" ]] && echo "     Escuchando en todas las interfaces: el ESP32 de la LAN usa http://<IP-de-este-PC>:$PORT"
echo
echo "  Pulsa Ctrl+C para detener todos los componentes."
echo

# Esperar al backend; si muere por su cuenta, salir con su código.
wait "$SERVER_PID" && rc=0 || rc=$?
SERVER_PID=""
(( rc == 0 )) || die "El backend se detuvo inesperadamente (código $rc)."
