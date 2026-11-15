"""Deterministic face provider for simulation and tests (no model, no real recognition).

- An image "contains a face" when it is not flat (grayscale std > 12): the face is the
  central 60 % of the image, with synthetic frontal landmarks.
- The embedding is a fixed random projection of the 8×8 downsampled, mean-centered image, so
  the same picture (or a slightly noisy copy) gives the same "identity" and unrelated pictures
  give near-orthogonal embeddings.
It must never be used to make real access decisions (``DCG_SIMULATION`` only).
"""

from __future__ import annotations

import cv2
import numpy as np

from app.vision.provider import DetectedFace, l2_normalize

_PROJECTION = np.random.RandomState(20261114).standard_normal((64, 512)).astype(np.float32)


class MockFaceProvider:
    name = "mock-v1"

    def analyze(self, image_bgr: np.ndarray) -> list[DetectedFace]:
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        if float(gray.std()) <= 12:
            return []
        h, w = gray.shape
        x1, y1, x2, y2 = 0.2 * w, 0.2 * h, 0.8 * w, 0.8 * h
        fw, fh = x2 - x1, y2 - y1
        kps = np.array([
            [x1 + 0.3 * fw, y1 + 0.35 * fh], [x1 + 0.7 * fw, y1 + 0.35 * fh], [x1 + 0.5 * fw, y1 + 0.55 * fh],
            [x1 + 0.35 * fw, y1 + 0.75 * fh], [x1 + 0.65 * fw, y1 + 0.75 * fh],
        ], dtype=np.float32)
        small = cv2.resize(gray, (8, 8), interpolation=cv2.INTER_AREA).astype(np.float32).reshape(-1)
        small -= small.mean()
        return [DetectedFace(bbox=(x1, y1, x2, y2), det_score=0.99, embedding=l2_normalize(small @ _PROJECTION),
                             kps=kps)]
