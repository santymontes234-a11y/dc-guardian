"""Vision package: provider selection (lazy singleton)."""

from __future__ import annotations

import os
import threading

# Second barrier against decompression bombs (must be set before OpenCV is first imported;
# ``images.declared_size`` is the primary check).
os.environ.setdefault("OPENCV_IO_MAX_IMAGE_PIXELS", str(4096 * 4096))

from app.core.config import get_settings
from app.vision.provider import DetectedFace, FaceProvider, cosine, l2_normalize

__all__ = ["DetectedFace", "FaceProvider", "cosine", "get_provider", "l2_normalize", "set_provider"]

_provider: FaceProvider | None = None
_lock = threading.Lock()


def _build() -> FaceProvider:
    s = get_settings()
    kind = s.face_provider
    if kind == "auto":
        kind = "mock" if s.env == "test" else "insightface"
    if kind == "mock":
        from app.vision.mock_provider import MockFaceProvider

        return MockFaceProvider()
    from app.vision.insightface_provider import InsightFaceProvider

    return InsightFaceProvider(s.face_model, s.data_dir / "models")


def get_provider() -> FaceProvider:
    global _provider
    if _provider is None:
        with _lock:
            if _provider is None:
                _provider = _build()
    return _provider


def set_provider(provider: FaceProvider | None) -> None:
    """Override the provider (tests); ``None`` resets to the configured one."""
    global _provider
    with _lock:
        _provider = provider
