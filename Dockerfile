# DC Guardian — imagen única: API FastAPI + frontend estático + visión facial (InsightFace, CPU).
# La webcam NO entra en el contenedor: la abre el navegador del kiosco y envía los fotogramas
# por HTTP a /api/v1/vision/verify. El ESP32 tampoco se dockeriza (firmware/).
#
#   docker compose build      → construye esta imagen
#   docker compose up -d      → ver docker-compose.yml

FROM python:3.12-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ORT_DISABLE_TELEMETRY=1

# libgomp1: OpenMP que usa onnxruntime en CPU.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1) Dependencias (capa cacheada mientras no cambie el lock).
COPY backend/requirements.lock.txt /tmp/requirements.lock.txt
RUN pip install -r /tmp/requirements.lock.txt \
 # insightface arrastra opencv-python (GUI/X11); comparte el módulo cv2 con la variante
 # headless. Se deja solo la headless, reinstalada para restaurar sus archivos de cv2.
 && pip uninstall -y opencv-python \
 && pip install --force-reinstall --no-deps \
      "$(grep -E '^opencv-python-headless==' /tmp/requirements.lock.txt | cut -d' ' -f1)" \
 && python -c "import cv2, onnxruntime, insightface; print('cv2', cv2.__version__, '| ort', onnxruntime.__version__)"

# 2) Código. data/ NUNCA se copia (BD, claves, biometría): llega como volumen en /data.
COPY backend/ /app/backend/
COPY frontend/ /app/frontend/
# El ESP32 virtual del modo simulación (app/sim) carga simulator/esp32_sim.py.
COPY simulator/ /app/simulator/
COPY docker/entrypoint.sh /usr/local/bin/dcg-entrypoint

# 3) Usuario sin privilegios y directorio de datos persistente.
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin dcg \
 && mkdir -p /data/models \
 && chown -R dcg:dcg /data \
 && chmod 0755 /usr/local/bin/dcg-entrypoint

USER dcg
WORKDIR /app/backend

ENV DCG_DATA_DIR=/data

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status == 200 else 1)"

ENTRYPOINT ["dcg-entrypoint"]
# Una sola réplica y un solo worker: WebSockets, limitador de login y puertas virtuales
# viven en la memoria del proceso.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
