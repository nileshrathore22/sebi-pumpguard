from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.constants import DISCLAIMER


class WithDisclaimer(BaseModel):
    disclaimer: str = DISCLAIMER


class ErrorBody(BaseModel):
    code: int
    message: str


class ErrorResponse(WithDisclaimer):
    error: ErrorBody


class HealthResponse(WithDisclaimer):
    status: str
    database: bool
    cache: bool


class TopFeature(BaseModel):
    feature: str
    value: float
    robust_z: float


class ScoreResponse(WithDisclaimer):
    symbol: str
    as_of_date: str
    score: float
    threshold: float
    flagged: bool
    model_version: str
    top_features: list[TopFeature]
    features: dict[str, float]
    explanation: str
    explanation_path: Literal["llm", "fallback"]


class HistoryPoint(BaseModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    score: float | None


class HistoryResponse(WithDisclaimer):
    symbol: str
    threshold: float
    points: list[HistoryPoint]


class StockOut(BaseModel):
    symbol: str
    name: str | None
    exchange: str
    sector: str | None
    market_cap_band: str | None


class StocksResponse(WithDisclaimer):
    stocks: list[StockOut]


class CaseOut(BaseModel):
    case_id: str
    symbol: str
    window_start: str
    window_end: str
    order_reference: str | None
    order_url: str | None
    description: str | None
    label: str
    verified: bool
    split: str
    synthetic: bool


class CasesResponse(WithDisclaimer):
    cases: list[CaseOut]


class ReplayPoint(BaseModel):
    date: str
    close: float
    volume: int
    score: float | None


class ReplayResponse(WithDisclaimer):
    case_id: str
    symbol: str
    split: str
    verified: bool
    mode: str
    window_start: str
    window_end: str
    detector: str
    threshold: float
    detected: bool
    first_flag_date: str | None
    lead_time_days: int | None
    series: list[ReplayPoint]


class AlertOut(BaseModel):
    symbol: str
    triggered_at: str
    score: float
    explanation_text: str
    status: str


class AlertsResponse(WithDisclaimer):
    alerts: list[AlertOut]


class BacktestRequest(BaseModel):
    source: Literal["synthetic", "db"] = "synthetic"
    mode: Literal["dry-run", "official"] = "dry-run"
    n_bootstrap: int = Field(500, ge=50, le=2000)
    include_periods: bool = False


class BacktestResponse(WithDisclaimer):
    result: dict[str, Any]
