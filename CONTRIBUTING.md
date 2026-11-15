# Cómo contribuir a DC Guardian

Gracias por tu interés. Es un proyecto académico; las contribuciones deben respetar su regla
fundamental y sus convenciones.

## Reglas que no se negocian

- **Registro 1** (`engineers`, `face_embeddings`) **nunca** concede acceso. El motor de acceso
  solo consulta el **Registro 2** (`authorization_requests`).
- **Fail-closed**: ante cualquier error o duda, la puerta permanece cerrada. Toda ruta nueva de
  apertura necesita pruebas que demuestren que falla cerrada.
- El ESP32 **no decide**: solo abre ante un `GRANTED` firmado para su propia sesión. No existe
  ni debe existir una orden remota de apertura.
- Nada de secretos, fotografías, embeddings ni bases de datos en git (`data/`, `.env` y
  `dcg_config.h` están ignorados).

## Convenciones de código

- Identificadores y comentarios en **inglés**; textos de interfaz y documentación en **español**.
- Estados persistidos en español y mayúsculas (`PENDIENTE`, `APROBADA`…), como `StrEnum` en
  `backend/app/models/enums.py`.
- Fechas en UTC con zona horaria (`app.db.types.UTCDateTime`).
- Capas: `api` (routers, sin lógica) → `services` (dominio) → `models`.
- Toda acción relevante se audita con `services.audit.record(...)`.
- Errores de dominio: `core.errors.DomainError(code, message, status)`.
- Variables de entorno con prefijo `DCG_` (documentarlas en `backend/.env.example`).
- Cambios de esquema: siempre con una migración Alembic nueva.
- Firmware: la lógica va en `lib/dcg_core` (C++ puro, probado en el PC); el código específico
  del ESP32 va en `src/`.

## Flujo de trabajo

1. Crea una rama desde `main`: `feat/…`, `fix/…`, `docs/…`.
2. Instala el entorno (ver [docs/installation.md](docs/installation.md)).
3. Antes de abrir el PR, ejecuta:
   ```bash
   cd backend && .venv/bin/pytest
   cd firmware/esp32-door && pio test -e native && pio run -e esp32dev
   ```
   Para compilar el firmware necesitas un `include/dcg_config.h`; copia el de ejemplo, pero no lo subas.
4. Si cambias la API o el protocolo del ESP32, actualiza [docs/api.md](docs/api.md) o
   [docs/protocolo-esp32.md](docs/protocolo-esp32.md) en el mismo PR. Los códigos de
   denegación son un contrato con el firmware y las páginas.
5. Mensajes de commit claros, en imperativo. Por ejemplo: `Add LCD screen for sensor errors`.

## Reportar problemas

Abre un *issue* con los pasos para reproducirlo, lo esperado, lo obtenido y los logs relevantes
(`docker compose logs dcguardian` o la consola serie). **No** incluyas secretos, tokens,
contraseñas ni datos biométricos. Las vulnerabilidades se reportan según [SECURITY.md](SECURITY.md).
