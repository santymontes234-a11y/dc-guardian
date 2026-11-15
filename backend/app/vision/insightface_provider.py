"""InsightFace provider (ArcFace 512-d) running on CPU through onnxruntime."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import numpy as np

from app.vision.provider import DetectedFace, l2_normalize

log = logging.getLogger(__name__)

FALLBACK_MODEL = "buffalo_s"


class InsightFaceProvider:
    def __init__(self, model: str, models_root: Path):
        self._model = model
        self._root = models_root
        self._app = None
        self._lock = threading.Lock()
        self.name = model

    def _load(self):
        from insightface.app import FaceAnalysis  # heavy import, only when needed

        last_exc: Exception | None = None
        for name in dict.fromkeys([self._model, FALLBACK_MODEL]):
            try:
                app = FaceAnalysis(name=name, root=str(self._root), allowed_modules=["detection", "recognition"],
                                   providers=["CPUExecutionProvider"])
                app.prepare(ctx_id=-1, det_size=(640, 640))
                self.name = name
                log.info("InsightFace model %s loaded from %s", name, self._root)
                return app
            except Exception as exc:  # noqa: BLE001 — try the fallback model
                log.warning("Cannot load InsightFace model %s: %s", name, exc)
                last_exc = exc
        raise RuntimeError("No InsightFace model could be loaded") from last_exc

    def warm_up(self) -> None:
        with self._lock:
            if self._app is None:
                self._app = self._load()

    def analyze(self, image_bgr: np.ndarray) -> list[DetectedFace]:
        self.warm_up()
        faces = self._app.get(image_bgr)
        out = []
        for f in faces:
            if getattr(f, "embedding", None) is None:
                continue
            out.append(DetectedFace(
                bbox=tuple(float(v) for v in f.bbox),
                det_score=float(f.det_score),
                embedding=l2_normalize(f.embedding),
                kps=None if f.kps is None else np.asarray(f.kps, dtype=np.float32),
            ))
        return out
