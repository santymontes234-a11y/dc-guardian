"""Safe image decoding. Images live only in memory and are never written to disk.

Decompression bombs: the declared width/height are read from the file header and checked
BEFORE ``cv2.imdecode`` allocates the pixel buffer (a 1 MB PNG can declare 20000×20000 px).
``OPENCV_IO_MAX_IMAGE_PIXELS`` (set in ``app.vision``) is a second barrier inside OpenCV.
"""

from __future__ import annotations

import struct

import cv2
import numpy as np

from app.core.errors import DomainError

MIN_SIDE = 64
MAX_SIDE = 1280  # images are downscaled to this after decoding
MAX_DECODE_SIDE = 4096
MAX_DECODE_PIXELS = 4096 * 4096
_JPEG, _PNG, _RIFF = b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"RIFF"


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    i, n = 2, len(data)
    while i + 4 <= n:
        if data[i] != 0xFF:
            return None
        while i < n and data[i] == 0xFF:  # fill bytes
            i += 1
        if i >= n:
            return None
        marker = data[i]
        i += 1
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:  # standalone markers
            continue
        if marker == 0xD9 or i + 2 > n:  # EOI before any frame header
            return None
        (length,) = struct.unpack(">H", data[i:i + 2])
        if length < 2:
            return None
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):  # SOFn
            if i + 7 > n:
                return None
            h, w = struct.unpack(">HH", data[i + 3:i + 7])
            return w, h
        i += length
    return None


def _png_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 24 or data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


def _webp_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 30 or data[8:12] != b"WEBP":
        return None
    chunk = data[12:16]
    if chunk == b"VP8 ":
        w, h = struct.unpack("<HH", data[26:30])
        return w & 0x3FFF, h & 0x3FFF
    if chunk == b"VP8L":
        b = data[21:25]
        w = 1 + (b[0] | (b[1] & 0x3F) << 8)
        h = 1 + (b[1] >> 6 | b[2] << 2 | (b[3] & 0x0F) << 10)
        return w, h
    if chunk == b"VP8X":
        w = 1 + int.from_bytes(data[24:27], "little")
        h = 1 + int.from_bytes(data[27:30], "little")
        return w, h
    return None


def declared_size(data: bytes) -> tuple[int, int] | None:
    """(width, height) from the header, or None if the format is unsupported/unreadable."""
    if data.startswith(_JPEG):
        return _jpeg_size(data)
    if data.startswith(_PNG):
        return _png_size(data)
    if data.startswith(_RIFF):
        return _webp_size(data)
    return None


def decode_image(data: bytes, max_bytes: int) -> np.ndarray:
    """Return a BGR image (longest side ≤ 1280 px) or raise ``DomainError``."""
    if not data:
        raise DomainError("IMAGE_EMPTY", "La imagen está vacía", 422)
    if len(data) > max_bytes:
        raise DomainError("IMAGE_TOO_LARGE", f"La imagen supera {max_bytes // (1024 * 1024)} MB", 413)
    if not data.startswith((_JPEG, _PNG, _RIFF)) or (data.startswith(_RIFF) and data[8:12] != b"WEBP"):
        raise DomainError("IMAGE_FORMAT", "Formato no soportado (usa JPEG, PNG o WebP)", 422)
    size = declared_size(data)
    if size is None:
        raise DomainError("IMAGE_DECODE", "No se pudo leer la imagen", 422)
    w, h = size
    if w > MAX_DECODE_SIDE or h > MAX_DECODE_SIDE or w * h > MAX_DECODE_PIXELS:
        raise DomainError("IMAGE_DIMENSIONS", f"La imagen supera {MAX_DECODE_SIDE}×{MAX_DECODE_SIDE} px", 422)
    img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise DomainError("IMAGE_DECODE", "No se pudo leer la imagen", 422)
    h, w = img.shape[:2]
    if min(h, w) < MIN_SIDE:
        raise DomainError("IMAGE_TOO_SMALL", "La imagen es demasiado pequeña", 422)
    scale = MAX_SIDE / max(h, w)
    if scale < 1:
        img = cv2.resize(img, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    return img
