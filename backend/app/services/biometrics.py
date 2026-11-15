"""Facial biometrics for REGISTRO 1: enrollment, sample management and 1:1 verification.

Privacy rules
- Face images are decoded in memory and discarded; nothing but the embedding is persisted.
- Embeddings are encrypted at rest and linked to the engineer only through the opaque
  ``engineers.face_embedding_reference`` (``face_embeddings`` holds no personal data).
- The API exposes sample metadata only, never embeddings.

Concurrency: image analysis is CPU-heavy, so it runs BEFORE the write session touches the
database (the session only issues ``BEGIN IMMEDIATE`` on its first statement).
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import DomainError, not_found
from app.core.security import decrypt_biometric, encrypt_biometric
from app.models import Engineer, FaceEmbedding
from app.models.engineer import EMBEDDING_DIM
from app.models.enums import EngineerStatus
from app.services import engineers as engineers_service
from app.services.context import ActorCtx
from app.vision import cosine, get_provider, l2_normalize
from app.vision.images import decode_image
from app.vision.quality import assess

log = logging.getLogger(__name__)

NEAR_IDENTICAL = 0.998  # two samples this similar are the same frame/photo, not new information


# ------------------------------------------------------------------ embedding (de)serialization
def _pack(embedding: np.ndarray) -> bytes:
    v = l2_normalize(embedding)
    if v.shape != (EMBEDDING_DIM,):
        raise ValueError(f"Embedding must have {EMBEDDING_DIM} dimensions")
    return encrypt_biometric(v.astype("<f4").tobytes())


def _unpack(blob: bytes) -> np.ndarray:
    v = np.frombuffer(decrypt_biometric(blob), dtype="<f4")
    if v.shape != (EMBEDDING_DIM,):
        raise ValueError("Corrupted embedding")
    return v


def _embeddings(eng: Engineer) -> list[np.ndarray]:
    return [_unpack(s.embedding_encrypted) for s in eng.face_embeddings] if eng.face_embedding_reference else []


# ------------------------------------------------------------------ image analysis
@dataclass
class AnalyzedImage:
    index: int
    filename: str | None
    accepted: bool = False
    quality: dict | None = None
    error_code: str | None = None
    error: str | None = None
    embedding: np.ndarray | None = field(default=None, repr=False)

    def public(self) -> dict:
        return {"index": self.index, "filename": self.filename, "accepted": self.accepted,
                "quality": self.quality, "error_code": self.error_code, "error": self.error}


def quality_check(data: bytes) -> dict:
    """Evaluate one image (live feedback while capturing). Nothing is stored."""
    s = get_settings()
    img = decode_image(data, s.image_max_bytes)
    faces = get_provider().analyze(img)
    out = assess(img, faces, s).public()
    out["image_height"], out["image_width"] = img.shape[:2]
    return out


def analyze_images(images: list[tuple[str | None, bytes]]) -> tuple[str, list[AnalyzedImage]]:
    """Decode, detect, check quality and embed each image. Returns (model name, per-image results)."""
    s = get_settings()
    provider = get_provider()
    results: list[AnalyzedImage] = []
    seen_hashes: set[str] = set()
    for i, (filename, data) in enumerate(images):
        r = AnalyzedImage(index=i, filename=(filename or None) and filename[:80])
        results.append(r)
        digest = hashlib.sha256(data).hexdigest()
        if digest in seen_hashes:
            r.error_code, r.error = "DUPLICATE_IMAGE", "Imagen repetida"
            continue
        seen_hashes.add(digest)
        try:
            img = decode_image(data, s.image_max_bytes)
        except DomainError as exc:
            r.error_code, r.error = exc.code, exc.message
            continue
        faces = provider.analyze(img)
        rep = assess(img, faces, s)
        r.quality = rep.public()
        if not rep.ok:
            r.error_code, r.error = rep.issues[0], "; ".join(rep.messages)
            continue
        emb = faces[0].embedding
        if any(o.embedding is not None and cosine(o.embedding, emb) > NEAR_IDENTICAL for o in results[:-1]):
            r.error_code, r.error = "NEAR_DUPLICATE", "Captura prácticamente idéntica a otra; cambia ligeramente la pose"
            continue
        r.embedding, r.accepted = emb, True
    return provider.name, results


# ------------------------------------------------------------------ enrollment
def _check_consistency(embs: list[np.ndarray], threshold: float) -> float:
    """Every pair of samples must look like the same person (min pairwise cosine)."""
    worst = min((cosine(embs[i], embs[j]) for i in range(len(embs)) for j in range(i + 1, len(embs))),
                default=1.0)
    if worst < threshold:
        raise DomainError("FACE_INCONSISTENT_SAMPLES",
                          "Las muestras no parecen ser de la misma persona; repite la captura", 422)
    return worst


def _find_duplicate(db: Session, eng: Engineer, embs: list[np.ndarray], model_name: str,
                    threshold: float) -> tuple[Engineer, float] | None:
    """Enrollment-only 1:N search: is this face already registered for another engineer?"""
    others = db.execute(
        select(Engineer).where(Engineer.id != eng.id, Engineer.face_embedding_reference.is_not(None))
    ).scalars().all()
    best: tuple[Engineer, float] | None = None
    for other in others:
        theirs = []
        for sample in other.face_embeddings:
            if sample.model_name != model_name:
                continue
            try:
                theirs.append(_unpack(sample.embedding_encrypted))
            except ValueError:  # wrong key or tampered row: skip it, never block other enrollments
                log.warning("Skipping undecryptable face sample id=%s in duplicate check", sample.id)
        if not theirs:
            continue
        score = float(np.mean([max(cosine(e, t) for t in theirs) for e in embs]))
        if score >= threshold and (best is None or score > best[1]):
            best = (other, score)
    return best


def _validate_enrollment(db: Session, eng: Engineer, results: list[AnalyzedImage], accepted: list[AnalyzedImage],
                         reports: list[dict], model_name: str, replace: bool):
    """Raise ``DomainError`` if this enrollment must be rejected; return the samples to store."""
    s = get_settings()
    existing = [] if replace else list(eng.face_embeddings) if eng.face_embedding_reference else []
    if existing and any(x.model_name != model_name for x in existing):
        raise DomainError("FACE_MODEL_CHANGED",
                          "Las muestras existentes son de otro modelo; registra de nuevo reemplazándolas", 409)
    total = len(existing) + len(accepted)
    if total < s.face_enroll_min_samples:
        raise DomainError(
            "FACE_INSUFFICIENT_SAMPLES",
            f"Se necesitan al menos {s.face_enroll_min_samples} capturas válidas (válidas: {len(accepted)})",
            422, details=reports,
        )
    if total > s.face_enroll_max_samples:
        if existing:
            raise DomainError("FACE_TOO_MANY_SAMPLES",
                              f"Máximo {s.face_enroll_max_samples} muestras por ingeniero; elimina alguna o reemplaza",
                              409, details=reports)
        # A fresh enrollment keeps the best-quality captures.
        accepted.sort(key=lambda r: r.quality["score"], reverse=True)
        for r in accepted[s.face_enroll_max_samples:]:
            r.accepted, r.error_code, r.error = False, "SURPLUS", "Descartada: se conservaron las de mayor calidad"
        accepted = accepted[: s.face_enroll_max_samples]
        reports = [r.public() for r in results]

    try:
        old_embs = [_unpack(x.embedding_encrypted) for x in existing]
    except ValueError:
        raise DomainError("FACE_DATA_CORRUPTED",
                          "Las muestras existentes no se pueden leer; registra de nuevo reemplazándolas", 409) from None
    _check_consistency(old_embs + [r.embedding for r in accepted], s.face_consistency_threshold)

    dup = _find_duplicate(db, eng, [r.embedding for r in accepted], model_name, s.face_duplicate_threshold)
    if dup is not None:
        other, score = dup
        # Generic message: naming the owner would turn enrollment into a 1:N identification
        # oracle ("whose face is this photo?"). The match is recorded in the audit log only.
        err = DomainError("FACE_ALREADY_REGISTERED",
                          "Este rostro ya está registrado para otro ingeniero. Consulta la auditoría.", 409)
        err.audit = {"matches_engineer_id": other.engineer_id, "score": round(score, 3)}
        raise err
    return accepted, reports, existing


def enroll(db: Session, ctx: ActorCtx, engineer_pk: int, images: list[tuple[str | None, bytes]],
           replace: bool) -> dict:
    s = get_settings()
    if not images:
        raise DomainError("NO_IMAGES", "Envía al menos una imagen", 422)
    if len(images) > s.face_enroll_max_samples * 2:
        raise DomainError("TOO_MANY_IMAGES", f"Máximo {s.face_enroll_max_samples * 2} imágenes por envío", 422)

    model_name, results = analyze_images(images)  # heavy work: no DB lock held yet
    reports = [r.public() for r in results]
    accepted = [r for r in results if r.accepted]

    eng = engineers_service.get(db, engineer_pk)
    engineers_service.ensure_not_erased(eng)
    try:
        accepted, reports, _existing = _validate_enrollment(db, eng, results, accepted, reports, model_name, replace)
    except DomainError as exc:
        duplicate = exc.code == "FACE_ALREADY_REGISTERED"
        ctx.audit(db, "engineer.face_duplicate_blocked" if duplicate else "engineer.face_enroll_failed",
                  "engineer", eng.id,
                  {"engineer_id": eng.engineer_id, "code": exc.code, "images": len(results),
                   "accepted": sum(r.accepted for r in results), "replace": replace,
                   **getattr(exc, "audit", {})})
        db.commit()
        raise

    replaced = bool(replace and eng.face_embedding_reference)
    if replace or not eng.face_embedding_reference:
        # Fresh profile with a new opaque reference (old samples, if any, are deleted).
        eng.face_embeddings.clear()
        db.flush()
        eng.face_embedding_reference = str(uuid.uuid4())
        db.flush()
    for r in accepted:
        eng.face_embeddings.append(FaceEmbedding(
            subject_ref=eng.face_embedding_reference, embedding_encrypted=_pack(r.embedding),
            model_name=model_name, quality_score=r.quality["score"], is_primary=False,
        ))
    db.flush()
    _refresh_primary(eng)
    eng.updated_at = ctx.now
    ctx.audit(db, "engineer.face_enrolled", "engineer", eng.id,
              {"engineer_id": eng.engineer_id, "model": model_name, "samples_added": len(accepted),
               "samples_total": len(eng.face_embeddings), "replaced": replaced,
               "images_rejected": len(results) - len(accepted)})
    db.commit()
    eng = engineers_service.get(db, eng.id)
    return {"engineer": eng, "model_name": model_name, "samples_added": len(accepted),
            "samples_total": eng.face_samples, "replaced": replaced, "images": reports}


def _refresh_primary(eng: Engineer) -> None:
    best = max(eng.face_embeddings, key=lambda x: x.quality_score or 0, default=None)
    for x in eng.face_embeddings:
        x.is_primary = x is best


def profile(db: Session, engineer_pk: int) -> dict:
    s = get_settings()
    eng = engineers_service.get(db, engineer_pk)
    samples = list(eng.face_embeddings) if eng.face_embedding_reference else []
    return {"face_embedding_reference": eng.face_embedding_reference, "samples": samples,
            "min_samples": s.face_enroll_min_samples, "max_samples": s.face_enroll_max_samples}


def delete_sample(db: Session, ctx: ActorCtx, engineer_pk: int, sample_id: int) -> Engineer:
    eng = engineers_service.get(db, engineer_pk)
    sample = next((x for x in eng.face_embeddings if x.id == sample_id), None)
    if sample is None or not eng.face_embedding_reference:
        raise not_found("FACE_SAMPLE_NOT_FOUND", "Muestra facial no encontrada")
    eng.face_embeddings.remove(sample)
    db.flush()
    if not eng.face_embeddings:
        eng.face_embedding_reference = None
    else:
        _refresh_primary(eng)
    eng.updated_at = ctx.now
    ctx.audit(db, "engineer.face_sample_deleted", "engineer", eng.id,
              {"engineer_id": eng.engineer_id, "sample_id": sample_id, "remaining": len(eng.face_embeddings)})
    db.commit()
    return engineers_service.get(db, eng.id)


def delete_all(db: Session, ctx: ActorCtx, engineer_pk: int) -> tuple[Engineer, int]:
    """Erase every biometric sample (the engineer keeps the personal record)."""
    eng = engineers_service.get(db, engineer_pk)
    if not eng.face_embedding_reference:
        raise DomainError("NO_FACE_DATA", "El ingeniero no tiene datos biométricos", 409)
    n = len(eng.face_embeddings)
    eng.face_embeddings.clear()
    db.flush()
    eng.face_embedding_reference = None
    eng.updated_at = ctx.now
    ctx.audit(db, "engineer.face_deleted", "engineer", eng.id, {"engineer_id": eng.engineer_id, "samples": n})
    db.commit()
    return engineers_service.get(db, eng.id), n


# ------------------------------------------------------------------ 1:1 verification
@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    score: float  # median of the per-frame best similarity (0 when nothing comparable)
    matches: int
    frames: int
    reason_code: str | None
    model_name: str | None = None


def verify(db: Session, engineer_pk: int, frames: list[bytes], *, allow_inactive: bool = False) -> VerifyResult:
    """1:1: do the frames show the engineer ``engineer_pk``? Fail-closed on any problem.

    Policy: exactly ``face_frames`` frames, of which ≥ ``face_min_matches`` have cosine ≥
    ``face_threshold`` against the best of the engineer's samples. A fixed frame count keeps the
    false-accept rate from growing with N and bounds the CPU spent per attempt.
    Basic liveness (academic): if ANY two frames are byte-identical or near-identical
    (re-encoded copies of one photo), the attempt fails. It does not stop advanced attacks
    (a printed photo moved in front of the camera, screens, masks).
    This function does NOT check authorizations: that is the access engine's job (Registro 2).
    """
    s = get_settings()
    n = len(frames)
    try:
        eng = db.get(Engineer, engineer_pk)
        if eng is None:
            return VerifyResult(False, 0.0, 0, n, "ENGINEER_NOT_FOUND")
        # ``allow_inactive`` is used ONLY for the exit of someone already inside (access engine):
        # a suspended engineer must still be able to prove identity to leave. Entry never sets it.
        if eng.status != EngineerStatus.ACTIVE and not (allow_inactive and eng.status != EngineerStatus.ERASED):
            return VerifyResult(False, 0.0, 0, n, "ENGINEER_NOT_ACTIVE")
        provider = get_provider()
        enrolled = [(x.model_name, _unpack(x.embedding_encrypted)) for x in eng.face_embeddings] \
            if eng.face_embedding_reference else []
        refs = [e for m, e in enrolled if m == provider.name]
        if not enrolled:
            return VerifyResult(False, 0.0, 0, n, "NO_FACE_ENROLLED")
        if not refs:
            return VerifyResult(False, 0.0, 0, n, "MODEL_MISMATCH", provider.name)
        if n == 0:
            return VerifyResult(False, 0.0, 0, 0, "NO_FRAMES", provider.name)
        if n != s.face_frames:
            return VerifyResult(False, 0.0, 0, n, "BAD_FRAME_COUNT", provider.name)
        if len({hashlib.sha256(f).digest() for f in frames}) < n:
            return VerifyResult(False, 0.0, 0, n, "LIVENESS_FAILED", provider.name)

        scores: list[float] = []
        embs: list[np.ndarray] = []
        multiple = False
        for data in frames:
            try:
                img = decode_image(data, s.image_max_bytes)
            except DomainError:
                continue
            faces = provider.analyze(img)
            if len(faces) != 1:
                multiple = multiple or len(faces) > 1
                continue
            emb = faces[0].embedding
            embs.append(emb)
            scores.append(max(cosine(emb, r) for r in refs))
        if not scores:
            return VerifyResult(False, 0.0, 0, n, "MULTIPLE_FACES" if multiple else "FACE_NOT_DETECTED", provider.name)
        # Any near-duplicate pair means replayed copies of one picture: deny the whole attempt
        # (counting copies as independent matches would let a single photo reach k).
        if any(cosine(embs[i], embs[j]) > NEAR_IDENTICAL
               for i in range(len(embs)) for j in range(i + 1, len(embs))):
            return VerifyResult(False, round(float(np.median(scores)), 4), 0, n, "LIVENESS_FAILED", provider.name)
        matches = sum(sc >= s.face_threshold for sc in scores)
        score = round(float(np.median(scores)), 4)
        ok = matches >= s.face_min_matches  # absolute: sending fewer frames never lowers the bar
        return VerifyResult(ok, score, matches, n, None if ok else "FACE_MISMATCH", provider.name)
    except Exception:  # noqa: BLE001 — fail-closed
        log.exception("Face verification failed for engineer %s", engineer_pk)
        return VerifyResult(False, 0.0, 0, n, "BIOMETRIC_ERROR")
