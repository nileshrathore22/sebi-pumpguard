from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_cache, get_db, settings_dep
from app.api.schemas import CasesResponse, ReplayResponse
from app.api.services import replay_from_db
from app.cache.redis_cache import Cache
from app.core.config import Settings
from app.detection.registry import DETECTORS
from app.ingestion.benchmark import cases_from_db

router = APIRouter(prefix="/cases", tags=["benchmark cases"])


@router.get("", response_model=CasesResponse)
def list_cases(
    split: str | None = Query(None, pattern="^(dev|test)$"),
    verified: bool | None = None,
    db: Session = Depends(get_db),
) -> CasesResponse:
    cases = cases_from_db(db)
    if split:
        cases = [c for c in cases if c.split == split]
    if verified is not None:
        cases = [c for c in cases if c.verified == verified]
    return CasesResponse(
        cases=[
            {  # type: ignore[misc]
                "case_id": c.case_id,
                "symbol": c.symbol,
                "window_start": c.window_start.isoformat(),
                "window_end": c.window_end.isoformat(),
                "order_reference": c.order_reference or None,
                "order_url": c.order_url or None,
                "description": c.description or None,
                "label": c.label,
                "verified": c.verified,
                "split": c.split,
                "synthetic": c.is_synthetic,
            }
            for c in cases
        ]
    )


@router.get("/{case_id}/replay", response_model=ReplayResponse)
def replay(
    case_id: str,
    detector: str = Query("isolation_forest", pattern="^(" + "|".join(DETECTORS) + ")$"),
    db: Session = Depends(get_db),
    cache: Cache = Depends(get_cache),
    settings: Settings = Depends(settings_dep),
) -> ReplayResponse:
    key = f"replay:{case_id}:{detector}"
    if (hit := cache.get_json(key)) is not None:
        return ReplayResponse(**hit)
    try:
        data = replay_from_db(db, case_id, detector)
    except KeyError as exc:
        raise HTTPException(404, f"unknown case {case_id}") from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    resp = ReplayResponse(**data)
    cache.set_json(key, resp.model_dump(), settings.cache_ttl_seconds)
    return resp
