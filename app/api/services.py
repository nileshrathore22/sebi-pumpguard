"""Backtest/replay helpers used by the API, with an in-process memo of backtest results."""

from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.evaluation.backtest import BacktestConfig, BacktestResult, replay_case, run_backtest
from app.ingestion.benchmark import BenchmarkCase, cases_from_db
from app.ingestion.loader import load_all_prices

_MEMO: dict[tuple[Any, ...], BacktestResult] = {}


def case_group(cases: list[BenchmarkCase], case: BenchmarkCase) -> tuple[list[BenchmarkCase], str]:
    """Never mix synthetic and real cases, or verified and unverified ones, in one backtest."""
    if case.is_synthetic:
        return [c for c in cases if c.is_synthetic], "dry-run"
    if case.verified:
        return [c for c in cases if not c.is_synthetic and c.verified], "official"
    return [c for c in cases if not c.is_synthetic], "dry-run"


def _fingerprint(prices: dict[str, pd.DataFrame]) -> tuple[Any, ...]:
    return tuple(sorted((s, len(df), str(df["date"].max())) for s, df in prices.items()))


def cached_backtest(
    prices: dict[str, pd.DataFrame], cases: list[BenchmarkCase], config: BacktestConfig
) -> BacktestResult:
    key = (
        _fingerprint(prices),
        tuple(sorted(c.case_id for c in cases)),
        config.mode,
        config.n_bootstrap,
        config.detectors,
    )
    if key not in _MEMO:
        _MEMO[key] = run_backtest(prices, cases, config)
    return _MEMO[key]


def replay_from_db(session: Session, case_id: str, detector: str) -> dict[str, Any]:
    all_cases = cases_from_db(session)
    case = next((c for c in all_cases if c.case_id == case_id), None)
    if case is None:
        raise KeyError(case_id)
    group, mode = case_group(all_cases, case)
    prices = load_all_prices(session)
    if case.symbol not in prices:
        raise LookupError(f"no price history for {case.symbol}")
    result = cached_backtest(prices, group, BacktestConfig(mode=mode, n_bootstrap=200))
    return replay_case(prices, group, case_id, result, detector_name=detector) | {"mode": mode}
