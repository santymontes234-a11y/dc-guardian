"""REGISTRO 1 — engineers and their facial biometrics. Nothing here grants access."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from app.api.deps import AdminCtx, AdminOnly, AdminOrAuditor, DbSession, ReadDb
from app.api.v1.uploads import read_images
from app.models.enums import EngineerStatus
from app.schemas.common import Page, PageParams, PathId, page_params
from app.schemas.engineers import (
    EngineerCreate,
    EngineerErase,
    EngineerOut,
    EngineerStatusChange,
    EngineerUpdate,
    EnrollmentOut,
    ErasureResult,
    FaceProfileOut,
    NextIdOut,
    StatusChangeResult,
)
from app.schemas.entrance import QrIssued, QrIssueIn, QrStatusOut
from app.services import biometrics
from app.services import qr as qr_service
from app.services import engineers as svc

router = APIRouter(prefix="/engineers", tags=["engineers (Registro 1)"])

MAX_UPLOADS = 10


@router.get("", response_model=Page[EngineerOut])
def list_engineers(
    _: AdminOrAuditor,
    db: ReadDb,
    page: Annotated[PageParams, Depends(page_params)],
    status: EngineerStatus | None = None,
    has_face: bool | None = None,
    q: Annotated[str | None, Query(max_length=80)] = None,
):
    """Erased (ELIMINADO) engineers are only listed when ``status=ELIMINADO`` is requested."""
    items, total = svc.list_(db, page, status=status, q=q, has_face=has_face)
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@router.get("/stats", response_model=dict[str, int])
def engineer_stats(_: AdminOrAuditor, db: ReadDb):
    return svc.stats(db)


@router.get("/next-id", response_model=NextIdOut)
def next_id(_: AdminOrAuditor, db: ReadDb):
    """Preview of the ID the next registration will receive (assigned for real on creation)."""
    return NextIdOut(engineer_id=svc.next_engineer_id(db))


@router.get("/by-code/{engineer_id}", response_model=EngineerOut)
def get_by_code(engineer_id: Annotated[str, Path(pattern=r"^[Ee][Nn][Gg]-[0-9]{4,6}$")], _: AdminOrAuditor,
                db: ReadDb):
    return svc.get_by_engineer_id(db, engineer_id)


@router.post("", response_model=EngineerOut, status_code=201)
def create_engineer(body: EngineerCreate, ctx: AdminCtx, db: DbSession):
    """Registers the engineer and assigns the next ``ENG-NNNN``. **Grants no access**:
    entering requires an approved authorization request (Registro 2)."""
    return svc.create(db, ctx, body)


@router.get("/{engineer_pk}", response_model=EngineerOut)
def get_engineer(engineer_pk: PathId, _: AdminOrAuditor, db: ReadDb):
    return svc.get(db, engineer_pk)


@router.patch("/{engineer_pk}", response_model=EngineerOut)
def update_engineer(engineer_pk: PathId, body: EngineerUpdate, ctx: AdminCtx, db: DbSession):
    return svc.update(db, ctx, engineer_pk, body)


@router.post("/{engineer_pk}/status", response_model=StatusChangeResult)
def change_engineer_status(engineer_pk: PathId, body: EngineerStatusChange, ctx: AdminCtx, db: DbSession):
    """Deactivating or suspending revokes approved and rejects pending requests."""
    eng, revoked, rejected = svc.change_status(db, ctx, engineer_pk, body.status, body.reason)
    return StatusChangeResult(engineer=eng, requests_revoked=revoked, requests_rejected=rejected)


@router.post("/{engineer_pk}/erase", response_model=ErasureResult)
def erase_engineer(engineer_pk: PathId, body: EngineerErase, ctx: AdminCtx, db: DbSession):
    """**Irreversible.** Deletes personal and biometric data; keeps an anonymous ``ENG-NNNN``
    row so the audit trail stays consistent. Closes open requests and unlinks active cards."""
    return svc.erase(db, ctx, engineer_pk, body.confirm_engineer_id, body.reason)


# ------------------------------------------------------------------ biometrics
@router.get("/{engineer_pk}/face", response_model=FaceProfileOut)
def get_face_profile(engineer_pk: PathId, _: AdminOrAuditor, db: ReadDb):
    """Sample metadata only; embeddings are never returned."""
    return biometrics.profile(db, engineer_pk)


@router.post("/{engineer_pk}/face", response_model=EnrollmentOut, openapi_extra={
    "requestBody": {"required": True, "content": {"multipart/form-data": {"schema": {
        "type": "object", "required": ["images"], "properties": {
            "images": {"type": "array", "items": {"type": "string", "format": "binary"},
                       "description": "3–5 capturas o fotos (JPEG/PNG/WebP, máx. 6 MB c/u)"},
            "replace": {"type": "boolean", "default": True}}}}}}})
async def enroll_face(engineer_pk: PathId, ctx: AdminCtx, db: DbSession, request: Request):
    """Registers facial samples: detection, quality, embedding, duplicate check, encrypted storage.
    The body is read only after authentication and kept in memory (images are never stored)."""
    form = await read_images(request, "images", MAX_UPLOADS)
    replace = form.fields.get("replace", "true").strip().lower() not in ("false", "0", "no", "off")
    return await run_in_threadpool(biometrics.enroll, db, ctx, engineer_pk, form.files, replace)


@router.delete("/{engineer_pk}/face", response_model=EngineerOut)
def delete_face_profile(engineer_pk: PathId, ctx: AdminCtx, db: DbSession):
    eng, _n = biometrics.delete_all(db, ctx, engineer_pk)
    return eng


@router.delete("/{engineer_pk}/face/{sample_id}", response_model=EngineerOut)
def delete_face_sample(engineer_pk: PathId, sample_id: PathId, ctx: AdminCtx, db: DbSession):
    return biometrics.delete_sample(db, ctx, engineer_pk, sample_id)


# ------------------------------------------------------------------ QR credential (main entrance)
@router.post("/{engineer_pk}/qr", response_model=QrIssued, status_code=201)
def issue_qr(engineer_pk: PathId, ctx: AdminCtx, db: DbSession, body: QrIssueIn | None = None):
    """Issues the engineer's QR for the main entrance and revokes the previous one. The QR text
    is returned **only now** (only its SHA-256 is stored). The QR identifies; it does not
    authorize: each scan also requires an approved authorization in force (Registro 2)."""
    body = body or QrIssueIn()
    return qr_service.issue(db, ctx, engineer_pk, body.expires_at,
                            valid_minutes=body.valid_minutes, single_use=body.single_use)


@router.get("/{engineer_pk}/qr", response_model=QrStatusOut)
def get_qr(engineer_pk: PathId, _: AdminOnly, db: ReadDb):
    """Whether the engineer has an active QR (prefix and dates; never the token)."""
    return qr_service.status(db, engineer_pk)


@router.delete("/{engineer_pk}/qr", status_code=204, response_class=Response)
def revoke_qr(engineer_pk: PathId, ctx: AdminCtx, db: DbSession):
    """Revokes the active QR (``404 QR_NOT_FOUND`` if there is none)."""
    qr_service.revoke(db, ctx, engineer_pk)
    return Response(status_code=204)
