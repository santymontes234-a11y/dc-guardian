import numpy as np
import pytest
from sqlalchemy import select

from app.core.security import decrypt_biometric
from app.models import AuditLog, AuthorizationRequest, Engineer, FaceEmbedding
from app.services import biometrics
from app.vision import get_provider
from tests.faces import blank, capture, files, person

BASE = "/api/v1/engineers"


def _enroll(f, eng, pattern, n=3, expected=200, replace=True, start=0):
    shots = [capture(pattern, start + i) for i in range(n)]
    r = f.c.post(f"{BASE}/{eng['id']}/face", files=files(*shots), data={"replace": str(replace).lower()})
    assert r.status_code == expected, r.text
    return r.json()


def test_mock_provider_in_tests():
    assert get_provider().name == "mock-v1"


def test_quality_endpoint(api):
    good = api.post("/api/v1/vision/quality", files={"image": ("a.jpg", capture(person(1), 0), "image/jpeg")}).json()
    assert good["ok"] is True and good["face_count"] == 1 and good["score"] > 0.5
    r = api.post("/api/v1/vision/quality", files={"image": ("a.png", blank(), "image/png")}).json()
    assert r["ok"] is False and r["issues"] == ["NO_FACE"]
    r = api.post("/api/v1/vision/quality", files={"image": ("b.jpg", capture(person(1), 0, blur=True), "image/jpeg")})
    assert "BLURRY" in r.json()["issues"]
    r = api.post("/api/v1/vision/quality", files={"image": ("d.jpg", capture(person(1), 0, dark=True), "image/jpeg")})
    assert "TOO_DARK" in r.json()["issues"]
    r = api.post("/api/v1/vision/quality", files={"image": ("x.txt", b"hola mundo", "text/plain")})
    assert r.status_code == 422 and r.json()["error"]["code"] == "IMAGE_FORMAT"


def test_enroll_stores_only_encrypted_embeddings(f, db):
    eng = f.engineer()
    out = _enroll(f, eng, person(1), n=4)
    assert out["samples_added"] == 4 and out["samples_total"] == 4 and out["model_name"] == "mock-v1"
    assert all(img["accepted"] for img in out["images"])
    e = out["engineer"]
    assert e["has_face"] is True and e["face_samples"] == 4
    ref = e["face_embedding_reference"]
    assert ref and len(ref) == 36

    rows = db.execute(select(FaceEmbedding)).scalars().all()
    assert {r.subject_ref for r in rows} == {ref}
    assert sum(r.is_primary for r in rows) == 1
    raw = rows[0].embedding_encrypted
    assert len(raw) > 2048 and np.frombuffer(decrypt_biometric(raw), "<f4").shape == (512,)
    # Biometric table has no personal data columns and no link to the engineer PK
    assert not {"engineer_id", "full_name", "institutional_email", "source_image_path"} & set(FaceEmbedding.__table__.c.keys())
    # Registration never creates authorizations
    assert db.query(AuthorizationRequest).count() == 0
    entry = db.execute(select(AuditLog).where(AuditLog.action == "engineer.face_enrolled")).scalar_one()
    assert ref not in entry.details_json

    profile = f.ok("GET", f"{BASE}/{eng['id']}/face")
    assert len(profile["samples"]) == 4 and "embedding" not in str(profile["samples"][0].keys())


def test_no_images_written_to_disk(f, tmp_path):
    from app.core.config import get_settings

    data_dir = get_settings().data_dir
    before = {p for p in data_dir.rglob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")}
    _enroll(f, f.engineer(), person(3))
    after = {p for p in data_dir.rglob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")}
    assert after == before


def test_insufficient_valid_samples_reports_each_image(f):
    eng = f.engineer()
    p = person(2)
    r = f.c.post(f"{BASE}/{eng['id']}/face", files=files(capture(p, 0), blank(), capture(p, 1, blur=True)))
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "FACE_INSUFFICIENT_SAMPLES"
    codes = [d["error_code"] for d in err["details"]]
    assert codes == [None, "NO_FACE", "BLURRY"]
    assert f.ok("GET", f"{BASE}/{eng['id']}")["has_face"] is False


def test_repeated_image_rejected(f):
    eng = f.engineer()
    shot = capture(person(4), 0)
    r = f.c.post(f"{BASE}/{eng['id']}/face", files=files(shot, shot, shot))
    assert r.status_code == 422
    assert [d["error_code"] for d in r.json()["error"]["details"]][1:] == ["DUPLICATE_IMAGE", "DUPLICATE_IMAGE"]


def test_inconsistent_samples_rejected(f):
    eng = f.engineer()
    r = f.c.post(f"{BASE}/{eng['id']}/face",
                 files=files(capture(person(5), 0), capture(person(6), 1), capture(person(7), 2)))
    assert r.status_code == 422 and r.json()["error"]["code"] == "FACE_INCONSISTENT_SAMPLES"


def test_same_face_cannot_be_registered_twice(f, db):
    a, b = f.engineer(), f.engineer()
    _enroll(f, a, person(8))
    out = _enroll(f, b, person(8), expected=409, start=10)
    assert out["error"]["code"] == "FACE_ALREADY_REGISTERED"
    assert a["engineer_id"] not in str(out)  # no 1:N identification oracle through the API
    assert f.ok("GET", f"{BASE}/{b['id']}")["has_face"] is False
    entry = db.execute(select(AuditLog).where(AuditLog.action == "engineer.face_duplicate_blocked")).scalar_one()
    assert a["engineer_id"] in entry.details_json  # the match is traceable in the audit log
    # A different person is fine; re-enrolling the same engineer is not a duplicate
    _enroll(f, b, person(9))
    _enroll(f, a, person(8), start=20)


def test_replace_rotates_reference_and_append_respects_limits(f):
    eng = f.engineer()
    first = _enroll(f, eng, person(11))["engineer"]["face_embedding_reference"]
    out = _enroll(f, eng, person(11), n=2, replace=False, start=5)
    assert out["samples_total"] == 5 and out["engineer"]["face_embedding_reference"] == first
    out = _enroll(f, eng, person(11), n=1, replace=False, start=8, expected=409)
    assert out["error"]["code"] == "FACE_TOO_MANY_SAMPLES"
    out = _enroll(f, eng, person(11), n=3, replace=True, start=12)
    assert out["replaced"] is True and out["samples_total"] == 3
    assert out["engineer"]["face_embedding_reference"] != first


def test_fresh_enrollment_keeps_best_five(f):
    eng = f.engineer()
    out = _enroll(f, eng, person(12), n=7)
    assert out["samples_total"] == 5
    assert [i["error_code"] for i in out["images"]].count("SURPLUS") == 2


def test_delete_samples_and_profile(f, db):
    eng = f.engineer()
    _enroll(f, eng, person(13))
    samples = f.ok("GET", f"{BASE}/{eng['id']}/face")["samples"]
    out = f.ok("DELETE", f"{BASE}/{eng['id']}/face/{samples[0]['id']}")
    assert out["face_samples"] == 2
    assert f.c.delete(f"{BASE}/{eng['id']}/face/99999").status_code == 404
    out = f.ok("DELETE", f"{BASE}/{eng['id']}/face")
    assert out["has_face"] is False and out["face_embedding_reference"] is None
    assert db.query(FaceEmbedding).count() == 0
    assert f.c.delete(f"{BASE}/{eng['id']}/face").status_code == 409


def test_erasure_deletes_biometrics(f, db):
    eng = f.engineer()
    _enroll(f, eng, person(14))
    res = f.ok("POST", f"{BASE}/{eng['id']}/erase", json={"confirm_engineer_id": eng["engineer_id"], "reason": "Baja"})
    assert res["face_samples_deleted"] == 3 and res["engineer"]["has_face"] is False
    assert db.query(FaceEmbedding).count() == 0
    r = f.c.post(f"{BASE}/{eng['id']}/face", files=files(*[capture(person(14), i) for i in range(3)]))
    assert r.status_code == 409 and r.json()["error"]["code"] == "ENGINEER_ERASED"


def test_auditor_cannot_touch_biometrics(f, auditor_api):
    eng = f.engineer()
    assert auditor_api.get(f"{BASE}/{eng['id']}/face").status_code == 200
    r = auditor_api.post(f"{BASE}/{eng['id']}/face", files=files(*[capture(person(15), i) for i in range(3)]))
    assert r.status_code == 403
    assert auditor_api.post("/api/v1/vision/quality",
                            files={"image": ("a.jpg", capture(person(15), 0), "image/jpeg")}).status_code == 403


# ------------------------------------------------------------------ 1:1 verification (access engine API)
def _verify(db, eng, frames):
    db.expire_all()
    return biometrics.verify(db, eng["id"], frames)


def test_verify_one_to_one(f, db):
    eng, other = f.engineer(), f.engineer()
    _enroll(f, eng, person(20))
    _enroll(f, other, person(21))
    res = _verify(db, eng, [capture(person(20), 100 + i) for i in range(5)])
    assert res.ok and res.matches >= 3 and res.reason_code is None and res.score > 0.9
    # Someone else's face (even an enrolled one) is a mismatch
    res = _verify(db, eng, [capture(person(21), 100 + i) for i in range(5)])
    assert not res.ok and res.reason_code == "FACE_MISMATCH"


@pytest.mark.parametrize("case,code", [
    ("no_enrollment", "NO_FACE_ENROLLED"), ("identical", "LIVENESS_FAILED"), ("no_face", "FACE_NOT_DETECTED"),
    ("too_few", "BAD_FRAME_COUNT"), ("too_many", "BAD_FRAME_COUNT"), ("suspended", "ENGINEER_NOT_ACTIVE"),
    ("garbage", "FACE_NOT_DETECTED"), ("replay_with_decoy", "LIVENESS_FAILED"),
])
def test_verify_fails_closed(f, db, case, code):
    eng = f.engineer()
    p = person(30)
    if case != "no_enrollment":
        _enroll(f, eng, p)
    frames = [capture(p, 200 + i) for i in range(5)]
    if case == "identical":
        frames = [frames[0]] * 5
    elif case == "no_face":
        frames = [blank(320 + i) for i in range(5)]
    elif case == "too_few":
        frames = frames[:2]  # the frame count is fixed: fewer frames never lower the bar
    elif case == "too_many":
        frames = [capture(p, 300 + i) for i in range(60)]  # more frames never add chances
    elif case == "suspended":
        f.ok("POST", f"{BASE}/{eng['id']}/status", json={"status": "SUSPENDIDO", "reason": "prueba"})
    elif case == "garbage":
        frames = [b"not an image %d" % i for i in range(5)]
    elif case == "replay_with_decoy":
        # 3 re-encodings of one photo (distinct bytes, same face) + 2 frames of someone else
        import cv2
        import numpy as np

        img = cv2.imdecode(np.frombuffer(frames[0], np.uint8), cv2.IMREAD_COLOR)
        copies = [cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])[1].tobytes() for q in (95, 90, 85)]
        frames = copies + [capture(person(99), 400), capture(person(98), 401)]
    res = _verify(db, eng, frames)
    assert res.ok is False and res.reason_code == code


def test_verify_unexpected_error_is_denied(f, db, monkeypatch):
    eng = f.engineer()
    _enroll(f, eng, person(31))
    monkeypatch.setattr(biometrics, "_unpack", lambda blob: (_ for _ in ()).throw(ValueError("tampered")))
    res = _verify(db, eng, [capture(person(31), i) for i in range(5)])
    assert res.ok is False and res.reason_code == "BIOMETRIC_ERROR"


def test_engineer_without_face_has_no_access_fields(db, f):
    eng = f.engineer()
    row = db.get(Engineer, eng["id"])
    assert not any("access" in c or "authorized" in c for c in Engineer.__table__.c.keys())
    assert row.face_embedding_reference is None


# ------------------------------------------------------------------ security review fixes
def test_upload_body_not_read_before_auth(client, monkeypatch):
    """A1: anonymous uploads are rejected before the body is parsed or spooled."""
    from app.api.v1 import uploads

    called = []
    monkeypatch.setattr(uploads, "MultipartParser", lambda *a, **k: called.append(1))
    big = b"\xff\xd8\xff" + b"0" * (2 * 1024 * 1024)
    r = client.post("/api/v1/vision/quality", files={"image": ("a.jpg", big, "image/jpeg")})
    assert r.status_code == 401 and not called
    r = client.post(f"{BASE}/1/face", files=files(big, big))
    assert r.status_code == 401 and not called


def test_uploads_never_spooled_to_disk(f, monkeypatch):
    """A1: >1 MB images stay in memory (Starlette would spool them to a temp file)."""
    import starlette.formparsers

    def no_disk(*a, **k):
        raise AssertionError("upload spooled to a temporary file")

    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", no_disk)
    eng = f.engineer()
    import cv2
    import numpy as np

    rng = np.random.RandomState(1)
    shots = []
    for i in range(3):  # noisy PNGs > 1 MB each, still recognised as the same "person"
        img = cv2.imdecode(np.frombuffer(capture(person(40), i, size=900), np.uint8), cv2.IMREAD_COLOR)
        img = np.clip(img.astype(int) + rng.randint(-3, 4, img.shape), 0, 255).astype(np.uint8)
        data = cv2.imencode(".png", img)[1].tobytes()
        assert len(data) > 1024 * 1024
        shots.append(data)
    r = f.c.post(f"{BASE}/{eng['id']}/face", files=[("images", (f"{i}.png", d, "image/png")) for i, d in enumerate(shots)])
    assert r.status_code == 200, r.text


def test_upload_limits(f, api):
    eng = f.engineer()
    huge = b"\xff\xd8\xff" + b"0" * (6 * 1024 * 1024 + 10)
    r = api.post("/api/v1/vision/quality", files={"image": ("a.jpg", huge, "image/jpeg")})
    assert r.status_code == 413
    r = api.post(f"{BASE}/{eng['id']}/face", files=files(*[capture(person(41), i) for i in range(11)]))
    assert r.status_code == 422 and r.json()["error"]["code"] == "TOO_MANY_IMAGES"
    r = api.post("/api/v1/vision/quality", json={"image": "x"})
    assert r.status_code == 415
    r = api.post("/api/v1/vision/quality", files={"other": ("a.jpg", capture(person(41), 0), "image/jpeg")})
    assert r.status_code == 422


def test_decompression_bomb_rejected_before_decoding(api, monkeypatch):
    """M2: a small PNG that declares 20000×20000 px is refused from its header."""
    import struct
    import zlib

    import cv2

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 20000, 20000, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(b"\x00" * 1000)) + chunk(b"IEND", b""))
    monkeypatch.setattr(cv2, "imdecode", lambda *a: (_ for _ in ()).throw(AssertionError("decoded")))
    r = api.post("/api/v1/vision/quality", files={"image": ("bomb.png", png, "image/png")})
    assert r.status_code == 422 and r.json()["error"]["code"] == "IMAGE_DIMENSIONS"


@pytest.mark.parametrize("env,error", [
    ({"DCG_FACE_MIN_MATCHES": "0"}, "face_min_matches"),
    ({"DCG_FACE_THRESHOLD": "-1"}, "face_threshold"),
    ({"DCG_FACE_MIN_MATCHES": "6", "DCG_FACE_FRAMES": "5"}, "MIN_MATCHES"),
    ({"DCG_FACE_DUPLICATE_THRESHOLD": "0.6"}, "DUPLICATE_THRESHOLD"),
    ({"DCG_ENV": "prod", "DCG_COOKIE_SECURE": "true", "DCG_FACE_PROVIDER": "mock"}, "mock face provider"),
    ({"DCG_ENV": "prod", "DCG_COOKIE_SECURE": "true", "DCG_SIMULATION": "true"}, "mock face provider"),
])
def test_biometric_settings_cannot_fail_open(monkeypatch, env, error):
    """M3/M4: misconfiguration is refused at startup instead of accepting any face."""
    import secrets

    from pydantic import ValidationError

    from app.core.config import Settings

    monkeypatch.setenv("DCG_JWT_SECRET", secrets.token_urlsafe(48))
    monkeypatch.setenv("DCG_MASTER_KEY", secrets.token_urlsafe(48))
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(ValidationError, match=error):
        Settings(_env_file=None)


def test_corrupted_sample_does_not_block_other_enrollments(f, db):
    """B4: one undecryptable row elsewhere must not turn every enrollment into a 500."""
    a, b = f.engineer(), f.engineer()
    _enroll(f, a, person(50))
    db.execute(FaceEmbedding.__table__.update().values(embedding_encrypted=b"tampered"))
    db.commit()
    _enroll(f, b, person(51))


def test_failed_enrollments_are_audited(f, db):
    """B5: rejections leave a trace (codes and counters only)."""
    eng = f.engineer()
    f.c.post(f"{BASE}/{eng['id']}/face", files=files(blank()))
    entry = db.execute(select(AuditLog).where(AuditLog.action == "engineer.face_enroll_failed")).scalar_one()
    assert "FACE_INSUFFICIENT_SAMPLES" in entry.details_json


@pytest.mark.parametrize("status,ok,code", [
    ("SUSPENDIDO", True, None), ("INACTIVO", True, None), ("ELIMINADO", False, "ENGINEER_NOT_ACTIVE"),
])
def test_verify_allow_inactive_is_identity_only(f, db, status, ok, code):
    """Exit flow: a suspended/inactive engineer inside can still prove identity; erased never."""
    eng = f.engineer()
    _enroll(f, eng, person(60))
    frames = [capture(person(60), 500 + i) for i in range(5)]
    if status == "ELIMINADO":
        f.ok("POST", f"{BASE}/{eng['id']}/erase", json={"confirm_engineer_id": eng["engineer_id"], "reason": "baja"})
    else:
        f.ok("POST", f"{BASE}/{eng['id']}/status", json={"status": status, "reason": "prueba"})
    assert _verify(db, eng, frames).reason_code == "ENGINEER_NOT_ACTIVE"  # default stays strict
    db.expire_all()
    res = biometrics.verify(db, eng["id"], frames, allow_inactive=True)
    assert res.ok is ok and res.reason_code == code
    # Still a real 1:1 check: someone else's face is refused even on exit
    if ok:
        other = [capture(person(61), 600 + i) for i in range(5)]
        assert biometrics.verify(db, eng["id"], other, allow_inactive=True).reason_code == "FACE_MISMATCH"
