from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import ReadDb
from app.core.config import get_settings

router = APIRouter(tags=["system"])


@router.get("/health")
def health(db: ReadDb):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "simulation": get_settings().simulation}
