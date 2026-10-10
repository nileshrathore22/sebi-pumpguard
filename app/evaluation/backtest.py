"""Retrospective backtest.

For each case: score every day from `window_start - pre_window_days` to `window_end`. The case
is *detected* if the score crosses the threshold on any day inside [window_start, window_end].
Lead time = days from window_start to the first flag inside the window. Controls are scored
over the same dates and count as false positives if they cross the threshold.

Leakage guards (see docs/EVALUATION.md, "Bias audit"):
* features are strictly trailing (Phase 2 tests);
* every model is fit only on rows before `fit_cutoff` = earliest test pre-window start;
* the supervised baseline only sees dev-case labels;
* the threshold is chosen by `select_threshold`, which rejects non-dev periods.
"""

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from app.core.constants import MIN_VERIFIED_CASES
from app.core.logging import get_logger
from app.detection.registry import DETECTORS, SUPERVISED, build_detector
from app.detection.threshold import PeriodScore, select_threshold
from app.evaluation.controls import ControlPeriod, build_controls
from app.evaluation.metrics import bootstrap_ci, confusion, metrics_from
from app.features.engineering import compute_universe_features
from app.ingestion.benchmark import BenchmarkCase

log = get_logger(__name__)


@dataclass
class BacktestConfig:
    mode: str = "dry-run"
    pre_window_days: int = 45
    controls_per_case: int = 2
    n_bootstrap: int = 1000
    seed: int = 42
    detectors: tuple[str, ...] = DETECTORS


@dataclass
class PeriodResult:
    period_id: str
    kind: str  # "case" | "control"
    symbol: str
    split: str
    window_start: str
    window_end: str
    max_score: float | None
    detected: bool
    first_flag_date: str | None
    lead_time_days: int | None
    flagged_in_pre_window: bool


@dataclass
class DetectorResult:
    detector: str
    threshold: float
    dev_f1: float
    test_metrics: dict[str, float | None]
    test_ci: dict[str, tuple[float, float] | None]
    test_confusion: dict[str, int]
    median_lead_time_days: float | None
    periods: list[PeriodResult] = field(default_factory=list)


@dataclass
class BacktestResult:
    mode: str
    fit_cutoff: str
    n_cases: dict[str, int]
    n_controls: dict[str, int]
    verified_cases: int
    warnings: list[str]
    detectors: list[DetectorResult]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def fit_cutoff(cases: list[BenchmarkCase], features: pd.DataFrame, pre_window_days: int) -> date:
    test = [c for c in cases if c.split == "test"]
    if not test:
        return max(features["date"]) + timedelta(days=1)
    return min(c.window_start for c in test) - timedelta(days=pre_window_days)


def dev_labels(features: pd.DataFrame, cases: list[BenchmarkCase]) -> np.ndarray:
    labels = np.zeros(len(features), dtype=int)
    for c in cases:
        if c.split != "dev":
            continue
        mask = (
            (features["symbol"] == c.symbol)
            & (features["date"] >= c.window_start)
            & (features["date"] <= c.window_end)
        )
        labels[mask.to_numpy()] = 1
    return labels


def _period_result(
    scored: pd.DataFrame,
    period_id: str,
    kind: str,
    symbol: str,
    split: str,
    start: date,
    end: date,
    threshold: float,
    pre_window_days: int,
) -> PeriodResult:
    s = scored[scored["symbol"] == symbol]
    pre = s[(s["date"] >= start - timedelta(days=pre_window_days)) & (s["date"] < start)]
    win = s[(s["date"] >= start) & (s["date"] <= end)]
    flags = win[win["score"] >= threshold]
    first = flags["date"].min() if len(flags) else None
    return PeriodResult(
        period_id=period_id,
        kind=kind,
        symbol=symbol,
        split=split,
        window_start=start.isoformat(),
        window_end=end.isoformat(),
        max_score=round(float(win["score"].max()), 4) if len(win) else None,
        detected=first is not None,
        first_flag_date=first.isoformat() if first is not None else None,
        lead_time_days=(first - start).days if first is not None else None,
        flagged_in_pre_window=bool((pre["score"] >= threshold).any()),
    )


def score_universe(
    features: pd.DataFrame, cases: list[BenchmarkCase], detector_name: str, cutoff: date
) -> pd.DataFrame:
    """Fit `detector_name` on rows before `cutoff` and score every row."""
    train_mask = features["date"] < cutoff
    train = features[train_mask]
    detector = build_detector(detector_name)
    labels = dev_labels(train, cases) if detector_name in SUPERVISED else None
    detector.fit(train, labels)
    out = features[["symbol", "date"]].copy()
    out["score"] = detector.score(features)
    return out


def run_backtest(
    prices: dict[str, pd.DataFrame],
    cases: list[BenchmarkCase],
    config: BacktestConfig | None = None,
    metadata: dict[str, dict[str, str | None]] | None = None,
) -> BacktestResult:
    config = config or BacktestConfig()
    warnings: list[str] = []
    cases = [c for c in cases if c.symbol in prices]
    verified = sum(c.verified for c in cases)
    if verified < MIN_VERIFIED_CASES:
        msg = f"only {verified} verified cases (< {MIN_VERIFIED_CASES}); results are not statistically meaningful"
        if config.mode == "dry-run":
            msg += " - DRY-RUN on unverified/synthetic data"
        warnings.append(msg)
        log.warning(msg)
    if not any(c.split == "dev" for c in cases):
        raise ValueError("backtest needs at least one dev-split case with price data")

    features = compute_universe_features(prices)
    cutoff = fit_cutoff(cases, features, config.pre_window_days)
    available = {s: (df["date"].min(), df["date"].max()) for s, df in prices.items()}
    controls: list[ControlPeriod] = build_controls(
        cases,
        available,
        per_case=config.controls_per_case,
        pre_window_days=config.pre_window_days,
        metadata=metadata,
    )
    if not controls:
        warnings.append("no negative controls available; false-positive rate cannot be estimated")

    results = []
    for name in config.detectors:
        scored = score_universe(features, cases, name, cutoff)

        def periods_at(t: float, scored: pd.DataFrame = scored) -> list[PeriodResult]:
            out = [
                _period_result(
                    scored,
                    c.case_id,
                    "case",
                    c.symbol,
                    c.split,
                    c.window_start,
                    c.window_end,
                    t,
                    config.pre_window_days,
                )
                for c in cases
            ]
            out += [
                _period_result(
                    scored,
                    k.control_id,
                    "control",
                    k.symbol,
                    k.split,
                    k.window_start,
                    k.window_end,
                    t,
                    config.pre_window_days,
                )
                for k in controls
            ]
            return out

        # 1) tune on dev only
        provisional = periods_at(100.0)
        dev_periods = [
            PeriodScore(
                p.period_id,
                p.split,
                p.max_score if p.max_score is not None else -1.0,
                p.kind == "case",
            )
            for p in provisional
            if p.split == "dev"
        ]
        tuned = select_threshold(dev_periods)
        # 2) apply unchanged to test
        periods = periods_at(tuned.threshold)
        test_cases = np.array(
            [p.detected for p in periods if p.kind == "case" and p.split == "test"]
        )
        test_ctrls = np.array(
            [p.detected for p in periods if p.kind == "control" and p.split == "test"]
        )
        conf = confusion(test_cases, test_ctrls)
        leads = [
            p.lead_time_days
            for p in periods
            if p.kind == "case" and p.split == "test" and p.lead_time_days is not None
        ]
        results.append(
            DetectorResult(
                detector=name,
                threshold=tuned.threshold,
                dev_f1=tuned.f1,
                test_metrics={
                    k: (round(v, 4) if v is not None else None)
                    for k, v in metrics_from(conf).items()
                },
                test_ci=bootstrap_ci(
                    test_cases, test_ctrls, n_boot=config.n_bootstrap, seed=config.seed
                ),
                test_confusion=asdict(conf),
                median_lead_time_days=float(np.median(leads)) if leads else None,
                periods=periods,
            )
        )
    if not any(c.split == "test" for c in cases):
        warnings.append("no test-split cases: test metrics are empty")

    return BacktestResult(
        mode=config.mode,
        fit_cutoff=cutoff.isoformat(),
        n_cases={s: sum(c.split == s for c in cases) for s in ("dev", "test")},
        n_controls={s: sum(k.split == s for k in controls) for s in ("dev", "test")},
        verified_cases=verified,
        warnings=warnings,
        detectors=results,
    )


def replay_case(
    prices: dict[str, pd.DataFrame],
    cases: list[BenchmarkCase],
    case_id: str,
    result: BacktestResult,
    detector_name: str = "isolation_forest",
    pre_window_days: int = 45,
    post_days: int = 20,
) -> dict[str, Any]:
    """Day-by-day series for one case using the same out-of-sample model as the backtest."""
    case = next((c for c in cases if c.case_id == case_id), None)
    if case is None:
        raise KeyError(case_id)
    det = next(d for d in result.detectors if d.detector == detector_name)
    features = compute_universe_features(prices)
    scored = score_universe(features, cases, detector_name, date.fromisoformat(result.fit_cutoff))
    start = case.window_start - timedelta(days=pre_window_days)
    end = case.window_end + timedelta(days=post_days)
    px = prices[case.symbol]
    px = px[(px["date"] >= start) & (px["date"] <= end)]
    s = scored[scored["symbol"] == case.symbol][["date", "score"]]
    merged = px.merge(s, on="date", how="left")
    period = next(p for p in det.periods if p.period_id == case_id)
    return {
        "case_id": case.case_id,
        "symbol": case.symbol,
        "split": case.split,
        "verified": case.verified,
        "window_start": case.window_start.isoformat(),
        "window_end": case.window_end.isoformat(),
        "detector": detector_name,
        "threshold": det.threshold,
        "detected": period.detected,
        "first_flag_date": period.first_flag_date,
        "lead_time_days": period.lead_time_days,
        "series": [
            {
                "date": r.date.isoformat(),
                "close": float(r.close),
                "volume": int(r.volume),
                "score": None if pd.isna(r.score) else float(r.score),
            }
            for r in merged.itertuples(index=False)
        ],
    }
