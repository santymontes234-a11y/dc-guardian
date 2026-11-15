"""Synthetic "faces" for the deterministic MockFaceProvider (simulation only).

A person is an 8×8 grayscale pattern; each capture adds a small perturbation, so captures of
the same person are similar but never identical (the basic liveness check rejects identical
frames) and different people are unrelated. Same generator as ``tests/faces.py``.
"""

from __future__ import annotations

import cv2
import numpy as np

STRANGER_SEED = 987_654


def person(seed: int) -> np.ndarray:
    return np.random.RandomState(seed).uniform(40, 215, (8, 8)).astype(np.float32)


def capture(pattern: np.ndarray, shot: int, size: int = 320) -> bytes:
    rng = np.random.RandomState(10_000 + shot)
    p = np.clip(pattern + rng.normal(0, 10, pattern.shape), 0, 255)
    img = cv2.resize(p, (size, size), interpolation=cv2.INTER_NEAREST)
    img = np.clip(img + rng.normal(0, 4, img.shape), 0, 255)
    ok, buf = cv2.imencode(".jpg", cv2.cvtColor(img.astype(np.uint8), cv2.COLOR_GRAY2BGR))
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return buf.tobytes()


def captures(seed: int, n: int, first_shot: int = 0) -> list[bytes]:
    pattern = person(seed)
    return [capture(pattern, first_shot + i) for i in range(n)]


def engineer_seed(engineer_pk: int) -> int:
    """Each demo engineer gets a stable synthetic identity."""
    return 1_000 + engineer_pk
