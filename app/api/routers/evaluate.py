from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_cache, get_db, settings_dep
from app.api.schemas import AlertsResponse, BacktestRequest, BacktestResponse
from app.api.services import cached_backtest
from app.cache.redis_cache import Cache
from app.core.config import Settings
from app.db.models import Alert
from app.evaluation.backtest import BacktestConfig
from app.ingestion.benchmark import cases_from_db, load_benchmark
from app.ingestion.loader import load_all_prices

router = APIRouter(tags=["evaluation"])


@router.post("/evaluate/backtest", response_model=BacktestResponse)
def backtest(
    req: BacktestRequest,
    db: Session = Depends(get_db),
    cache: Cache = Depends(get_cache),
    settings: Settings = Depends(settings_dep),
) -> BacktestResponse:
    if req.source == "synthetic" and req.mode == "official":
        raise HTTPException(400, "synthetic fixtures can never produce an official result")
    key = f"backtest:{req.model_dump_json()}"
    if (hit := cache.get_json(key)) is not None:
        return BacktestResponse(result=hit)
    if req.source == "synthetic":
        from app.ingestion.synthetic import generate_synthetic_universe

        prices = generate_synthetic_universe().prices
        cases = load_benchmark(settings.synthetic_cases_path, "dry-run").accepted
    else:
        prices = load_all_prices(db)
        cases = [c for c in cases_from_db(db) if not c.is_synthetic]
        if req.mode == "official":
            cases = [c for c in cases if c.verified]
    if not cases:
        raise HTTPException(409, f"no cases available for source={req.source} mode={req.mode}")
    try:
        result = cached_backtest(
            prices, cases, BacktestConfig(mode=req.mode, n_bootstrap=req.n_bootstrap)
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    data: dict[str, Any] = result.to_dict()
    if not req.include_periods:
        for d in data["detectors"]:
            d.pop("periods", None)
    cache.set_json(key, data, settings.cache_ttl_seconds)
    return BacktestResponse(result=data)


@router.get("/alerts", response_model=AlertsResponse)
def alerts(limit: int = 50, db: Session = Depends(get_db)) -> AlertsResponse:
    rows = (
        db.query(Alert)
        .order_by(Alert.triggered_at.desc(), Alert.score.desc())
        .limit(min(limit, 500))
        .all()
    )
    return AlertsResponse(
        alerts=[
            {  # type: ignore[misc]
                "symbol": a.symbol,
                "triggered_at": a.triggered_at.isoformat(),
                "score": a.score,
                "explanation_text": a.explanation_text,
                "status": a.status,
            }
            for a in rows
        ]
    )
