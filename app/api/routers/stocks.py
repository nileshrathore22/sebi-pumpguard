from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_cache, get_db, settings_dep
from app.api.schemas import HistoryResponse, ScoreResponse, StockOut, StocksResponse
from app.cache.redis_cache import Cache
from app.core.config import Settings
from app.db.models import AnomalyScore, PriceHistory, Stock
from app.explain.graph import explain
from app.explain.llm import get_llm_client
from app.explain.payload import build_payload
from app.jobs import current_threshold

router = APIRouter(prefix="/stocks", tags=["stocks"])
SYMBOL = Path(
    ..., pattern=r"^[A-Za-z0-9_&.-]{1,32}$", description="NSE symbol, e.g. SUZLON or SYNTH_09"
)


@router.get("", response_model=StocksResponse)
def list_stocks(db: Session = Depends(get_db)) -> StocksResponse:
    rows = db.scalars(select(Stock).order_by(Stock.symbol)).all()
    return StocksResponse(
        stocks=[
            StockOut(
                symbol=r.symbol,
                name=r.name,
                exchange=r.exchange,
                sector=r.sector,
                market_cap_band=r.market_cap_band,
            )
            for r in rows
        ]
    )


@router.get("/{symbol}/score", response_model=ScoreResponse)
def get_score(
    symbol: str = SYMBOL,
    as_of: date | None = Query(None, description="defaults to the latest scored date"),
    db: Session = Depends(get_db),
    cache: Cache = Depends(get_cache),
    settings: Settings = Depends(settings_dep),
) -> ScoreResponse:
    symbol = symbol.upper()
    key = f"score:{settings.model_version}:{symbol}:{as_of or 'latest'}"
    if (hit := cache.get_json(key)) is not None:
        return ScoreResponse(**hit)
    q = select(AnomalyScore).where(
        AnomalyScore.symbol == symbol, AnomalyScore.model_version == settings.model_version
    )
    if as_of:
        q = q.where(AnomalyScore.as_of_date <= as_of)
    row = db.scalars(q.order_by(AnomalyScore.as_of_date.desc()).limit(1)).first()
    if row is None:
        raise HTTPException(404, f"no anomaly score for {symbol}")
    threshold = current_threshold(settings)
    top = row.feature_snapshot.get("top_features", [])
    payload = build_payload(
        symbol=symbol,
        as_of_date=row.as_of_date.isoformat(),
        score=row.score,
        threshold=threshold,
        top_features=top,
        model_version=row.model_version,
    )
    expl = explain(payload, get_llm_client(settings))
    resp = ScoreResponse(
        symbol=symbol,
        as_of_date=row.as_of_date.isoformat(),
        score=round(row.score, 2),
        threshold=threshold,
        flagged=row.score >= threshold,
        model_version=row.model_version,
        top_features=top,
        features=row.feature_snapshot.get("features", {}),
        explanation=expl["text"],
        explanation_path=expl["path"],
    )
    cache.set_json(key, resp.model_dump(), settings.cache_ttl_seconds)
    return resp


@router.get("/{symbol}/history", response_model=HistoryResponse)
def get_history(
    symbol: str = SYMBOL,
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
    cache: Cache = Depends(get_cache),
    settings: Settings = Depends(settings_dep),
) -> HistoryResponse:
    symbol = symbol.upper()
    if start and end and start > end:
        raise HTTPException(400, "start must be on or before end")
    key = f"history:{settings.model_version}:{symbol}:{start}:{end}"
    if (hit := cache.get_json(key)) is not None:
        return HistoryResponse(**hit)
    q = (
        select(PriceHistory, AnomalyScore.score)
        .outerjoin(
            AnomalyScore,
            (AnomalyScore.symbol == PriceHistory.symbol)
            & (AnomalyScore.as_of_date == PriceHistory.date)
            & (AnomalyScore.model_version == settings.model_version),
        )
        .where(PriceHistory.symbol == symbol)
        .order_by(PriceHistory.date)
    )
    if start:
        q = q.where(PriceHistory.date >= start)
    if end:
        q = q.where(PriceHistory.date <= end)
    rows = db.execute(q).all()
    if not rows:
        raise HTTPException(404, f"no price history for {symbol}")
    points = [
        {
            "date": p.date.isoformat(),
            "open": p.open,
            "high": p.high,
            "low": p.low,
            "close": p.close,
            "volume": p.volume,
            "score": score,
        }
        for p, score in rows
    ]
    resp = HistoryResponse(symbol=symbol, threshold=current_threshold(settings), points=points)  # type: ignore[arg-type]
    cache.set_json(key, resp.model_dump(), settings.cache_ttl_seconds)
    return resp
