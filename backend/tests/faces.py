"""Synthetic "faces" for the deterministic MockFaceProvider.

A person is an 8×8 grayscale pattern; each capture adds a small perturbation so captures of the
same person are similar (cos ≈ 0.95+) but not identical, and different people are unrelated.
"""

import cv2
import numpy as np


def person(seed: int) -> np.ndarray:
    return np.random.RandomState(seed).uniform(40, 215, (8, 8)).astype(np.float32)


def capture(pattern: np.ndarray, shot: int, *, size: int = 320, blur: bool = False, dark: bool = False) -> bytes:
    rng = np.random.RandomState(10_000 + shot)
    p = np.clip(pattern + rng.normal(0, 10, pattern.shape), 0, 255)
    img = cv2.resize(p, (size, size), interpolation=cv2.INTER_NEAREST)
    img = np.clip(img + rng.normal(0, 4, img.shape), 0, 255)
    if blur:
        img = cv2.GaussianBlur(img, (0, 0), 12)
    if dark:
        img = img * 0.28
    ok, buf = cv2.imencode(".jpg", cv2.cvtColor(img.astype(np.uint8), cv2.COLOR_GRAY2BGR))
    assert ok
    return buf.tobytes()


def blank(size: int = 320) -> bytes:
    ok, buf = cv2.imencode(".png", np.full((size, size, 3), 128, np.uint8))
    return buf.tobytes()


def files(*images: bytes) -> list:
    return [("images", (f"c{i}.jpg", data, "image/jpeg")) for i, data in enumerate(images)]
