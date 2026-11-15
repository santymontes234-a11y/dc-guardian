"""Image/face quality checks used before accepting a registration sample."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import cv2
import numpy as np

from app.core.config import Settings
from app.vision.provider import DetectedFace

ISSUE_MESSAGES = {
    "NO_FACE": "No se detectó ningún rostro",
    "MULTIPLE_FACES": "Hay más de un rostro en la imagen",
    "LOW_CONFIDENCE": "El rostro no se distingue con claridad",
    "FACE_TOO_SMALL": "Acércate a la cámara: el rostro es demasiado pequeño",
    "FACE_CUT": "El rostro está cortado por el borde de la imagen",
    "BLURRY": "La imagen está desenfocada o movida",
    "TOO_DARK": "Falta iluminación",
    "TOO_BRIGHT": "Exceso de iluminación o contraluz",
    "NOT_FRONTAL": "Mira de frente a la cámara",
}


@dataclass
class QualityReport:
    ok: bool
    score: float  # 0..1, higher is better
    issues: list[str] = field(default_factory=list)
    face_count: int = 0
    det_score: float | None = None
    face_px: int | None = None
    sharpness: float | None = None
    brightness: float | None = None
    yaw_ratio: float | None = None
    bbox: tuple[float, float, float, float] | None = None

    @property
    def messages(self) -> list[str]:
        return [ISSUE_MESSAGES[i] for i in self.issues]

    def public(self) -> dict:
        d = asdict(self)
        d["messages"] = self.messages
        return d


def _crop(img: np.ndarray, bbox) -> np.ndarray:
    h, w = img.shape[:2]
    x1, y1, x2, y2 = (int(round(v)) for v in bbox)
    x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
    return img[y1:y2, x1:x2]


def _yaw_ratio(kps: np.ndarray) -> float:
    """Horizontal offset of the nose from the eye midpoint, relative to the eye distance."""
    left_eye, right_eye, nose = kps[0], kps[1], kps[2]
    eye_dist = float(np.linalg.norm(right_eye - left_eye))
    if eye_dist < 1:
        return 1.0
    return abs(float(nose[0] - (left_eye[0] + right_eye[0]) / 2)) / eye_dist


def assess(img: np.ndarray, faces: list[DetectedFace], s: Settings) -> QualityReport:
    rep = QualityReport(ok=False, score=0.0, face_count=len(faces))
    if not faces:
        rep.issues.append("NO_FACE")
        return rep
    if len(faces) > 1:
        rep.issues.append("MULTIPLE_FACES")
        return rep

    face = faces[0]
    h, w = img.shape[:2]
    rep.bbox = tuple(round(float(v), 1) for v in face.bbox)
    rep.det_score = round(face.det_score, 3)
    rep.face_px = int(min(face.width, face.height))
    if face.det_score < s.face_min_det_score:
        rep.issues.append("LOW_CONFIDENCE")
    if rep.face_px < s.face_min_size_px:
        rep.issues.append("FACE_TOO_SMALL")
    x1, y1, x2, y2 = face.bbox
    margin = 0.04 * min(w, h)
    if x1 < -margin or y1 < -margin or x2 > w + margin or y2 > h + margin:
        rep.issues.append("FACE_CUT")

    crop = _crop(img, face.bbox)
    if crop.size:
        gray = cv2.cvtColor(cv2.resize(crop, (112, 112), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        rep.sharpness = round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 1)
        rep.brightness = round(float(gray.mean()), 1)
        if rep.sharpness < s.face_min_sharpness:
            rep.issues.append("BLURRY")
        if rep.brightness < 40:
            rep.issues.append("TOO_DARK")
        elif rep.brightness > 220:
            rep.issues.append("TOO_BRIGHT")
    if face.kps is not None:
        rep.yaw_ratio = round(_yaw_ratio(face.kps), 3)
        if rep.yaw_ratio > s.face_max_yaw_ratio:
            rep.issues.append("NOT_FRONTAL")

    # Combined score: detector confidence, size, sharpness and frontality.
    size_term = min(1.0, rep.face_px / (2.5 * s.face_min_size_px))
    sharp_term = min(1.0, (rep.sharpness or 0) / (4 * s.face_min_sharpness))
    yaw_term = 1.0 - min(1.0, (rep.yaw_ratio or 0) / max(s.face_max_yaw_ratio, 1e-3)) * 0.5
    rep.score = round(0.4 * face.det_score + 0.2 * size_term + 0.25 * sharp_term + 0.15 * yaw_term, 3)
    rep.ok = not rep.issues
    return rep
