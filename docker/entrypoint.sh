#!/bin/sh
# Arranque del contenedor: aplica las migraciones pendientes y ejecuta el comando (uvicorn).
# La semilla y el administrador se crean a mano, una sola vez (ver README § Docker).
set -eu
cd /app/backend
echo "[dcg] aplicando migraciones (alembic upgrade head)…"
alembic upgrade head
exec "$@"
