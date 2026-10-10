from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_cache, get_db
from app.api.schemas import HealthResponse
from app.cache.redis_cache import Cache

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(db: Session = Depends(get_db), cache: Cache = Depends(get_cache)) -> HealthResponse:
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return HealthResponse(status="ok" if db_ok else "degraded", database=db_ok, cache=cache.ping())
