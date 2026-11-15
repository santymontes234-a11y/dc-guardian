# Política de seguridad

DC Guardian es un **prototipo académico**. Implementa controles de seguridad reales, pero
**no está preparado para proteger instalaciones reales**.

## Reportar una vulnerabilidad

No abras un *issue* público. Usa **GitHub → Security → Report a vulnerability** (aviso privado)
en este repositorio, o contacta con el autor indicado en el README. Incluye:

- Componente afectado: backend, frontend, firmware o Docker.
- Pasos para reproducirla e impacto.
- Si es posible, una propuesta de corrección.

Se intentará responder en 7 días. No incluyas datos personales ni biométricos reales en el reporte.

## Versiones soportadas

Solo la rama `main`.

## Modelo de seguridad (resumen)

| Área | Medida |
|---|---|
| Decisión de acceso | Solo el backend decide; solo el Registro 2 concede acceso; *fail-closed* |
| ESP32 ↔ backend | Peticiones y respuestas firmadas con HMAC-SHA256, timestamp (±30 s), nonce de un solo uso, `session_id` ligado; sin orden remota de apertura |
| Secretos de dispositivo | Cifrados en reposo (Fernet con `DCG_MASTER_KEY`); se muestran una sola vez; rotación disponible |
| Administradores | bcrypt; JWT en cookie `HttpOnly` + `SameSite=Strict` (+ `Secure` en prod); bloqueo por intentos; límite por IP; roles `admin` y `auditor` |
| WebSocket | Cookie con comprobación de `Origin`, o token de kiosco (solo eventos `access.*`) |
| Biometría | Solo embeddings, nunca fotos; fotogramas del kiosco en memoria; borrado de datos personales y biométricos |
| Auditoría | Cadena de hashes con clave, verificable (`/audit/verify`) |
| Producción | El backend no arranca sin secretos fuertes, sin `COOKIE_SECURE` o con el proveedor facial *mock* |
| Docker | Usuario sin root, FS de solo lectura, `no-new-privileges`, sin capabilities; `data/` y `.env` fuera de la imagen |

## Limitaciones conocidas

- El UID de MIFARE Classic es clonable: por eso solo identifica la tarjeta y nunca autoriza por sí solo.
- Sin TLS por defecto: en la LAN se puede **leer** el tráfico, pero no falsificarlo ni reinyectarlo.
  Para usar el kiosco desde otro equipo, despliega HTTPS con un proxy inverso.
- El secreto del ESP32 está en su flash sin cifrar (sin *flash encryption* ni *secure boot*).
  Si pierdes un dispositivo, rota su secreto.
- *Liveness* básica (rechaza capturas idénticas); no resiste ataques de presentación elaborados.
- El umbral facial (`DCG_FACE_THRESHOLD`) no está calibrado con una población real.
- Los firmwares `esp32dev-bench` y `esp32dev-diag` permiten inyectar lecturas o mover el servo:
  **nunca** en una puerta real.

## Datos que nunca deben subirse

`backend/.env`, `.env`, `data/` (BD, `.dev_keys.json`, modelos), `firmware/**/include/dcg_config.h`,
fotografías, embeddings, contraseñas, tokens y claves WiFi. Si alguno se publica por error,
**rota** el secreto afectado: borrarlo del historial no basta.
