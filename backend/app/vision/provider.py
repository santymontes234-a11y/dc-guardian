"""Face provider interface. The rest of the system depends only on this module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class DetectedFace:
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 (pixels)
    det_score: float
    embedding: np.ndarray  # (512,) float32, L2-normalized
    kps: np.ndarray | None = None  # (5, 2): left eye, right eye, nose, left mouth, right mouth

    @property
    def width(self) -> float:
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self) -> float:
        return self.bbox[3] - self.bbox[1]


class FaceProvider(Protocol):
    name: str  # stored with every embedding; embeddings of different models are not comparable

    def analyze(self, image_bgr: np.ndarray) -> list[DetectedFace]:
        """Detect every face in the image and compute its embedding."""
        ...


def l2_normalize(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32).reshape(-1)
    n = float(np.linalg.norm(v))
    if not np.isfinite(n) or n < 1e-6:
        raise ValueError("Degenerate embedding")
    return v / n


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Both vectors must already be L2-normalized."""
    return float(np.dot(a, b))
