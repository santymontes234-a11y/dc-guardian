from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from app.api.deps import AdminOnly
from app.api.v1.uploads import read_images
from app.core.errors import DomainError
from app.schemas.engineers import QualityOut
from app.services import biometrics

router = APIRouter(prefix="/vision", tags=["vision"])


@router.post("/quality", response_model=QualityOut, openapi_extra={
    "requestBody": {"required": True, "content": {"multipart/form-data": {"schema": {
        "type": "object", "required": ["image"],
        "properties": {"image": {"type": "string", "format": "binary"}}}}}}})
async def image_quality(_: AdminOnly, request: Request):
    """Evaluates one capture (single face, size, sharpness, lighting, pose). Nothing is stored;
    the body is read only after authentication and kept in memory."""
    form = await read_images(request, "image", 1)
    if not form.files:
        raise DomainError("NO_IMAGES", "Envía una imagen en el campo «image»", 422)
    return await run_in_threadpool(biometrics.quality_check, form.files[0][1])
