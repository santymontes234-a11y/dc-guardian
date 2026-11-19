from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import ReadDb

router = APIRouter(tags=["system"])


@router.get("/health")
def health(db: ReadDb):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
