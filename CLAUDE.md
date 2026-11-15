# DC Guardian — Convenciones del proyecto

Sistema académico de control de acceso a un Data Center (ESP32 + RC522 + HC-SR04 + SG90,
FastAPI, InsightFace, SQLite). El diseño aprobado está en `docs/FASE1_ARQUITECTURA.md`;
es la fuente de verdad para modelos, API, protocolo y plan de fases.

## Regla fundamental
- **Registro 1** (`engineers`, `face_embeddings`) NUNCA concede acceso.
- **Registro 2** (`authorization_requests`) es lo único que el motor de acceso consulta.
- Fail-closed: ante cualquier error o duda, la puerta permanece cerrada.

## Entorno
- Python **3.12** (no el 3.14 del sistema: InsightFace/onnxruntime). Venv en `backend/.venv`.
- `uv` está en `.tools/bin/uv`.
- Comandos (desde `backend/`):
  - Instalar: `../.tools/bin/uv sync`
  - Tests: `.venv/bin/pytest`
  - Migrar: `.venv/bin/alembic upgrade head`
  - Servidor: `.venv/bin/uvicorn app.main:app --reload`
  - Semilla: `.venv/bin/python -m scripts.seed`
  - Admin: `.venv/bin/python -m scripts.create_admin <usuario>`

## Convenciones de código
- Identificadores y comentarios de código en inglés; textos de UI y documentación en español.
- Valores de estado persistidos en español y mayúsculas (`PENDIENTE`, `APROBADA`, ...),
  definidos como `StrEnum` en `app/models/enums.py`.
- Fechas siempre en UTC con zona horaria (`app.db.types.UTCDateTime`).
- Capas: `api` (routers, sin lógica) → `services` (dominio) → `repositories`/`models`.
- Toda acción relevante se registra con `services.audit.record(...)`.
- Errores de dominio: lanzar `core.errors.DomainError(code, message, status)`.
- Variables de entorno con prefijo `DCG_` (ver `backend/.env.example`).
- Ningún secreto, foto o base de datos en git (`data/` está ignorado).

## Subagentes
Definidos en `.claude/agents/`. Cada uno tiene archivos propios; los cambios que cruzan
fronteras pasan por `integration-agent`. `security-agent` revisa al cierre de cada fase.
