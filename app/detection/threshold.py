"""Threshold selection on the DEV split only.

The routine refuses any input that is not from the dev split, so it is structurally
impossible for test-split cases (or their controls) to influence the threshold.
"""

from dataclasses import dataclass

import numpy as np

# Scores are percentiles, so the interesting region is the top few percent: use a coarse grid
# below 95 and a fine one above it.
DEFAULT_GRID = tuple(
    sorted(
        {round(float(x), 2) for x in np.arange(50.0, 95.0, 0.5)}
        | {round(float(x), 2) for x in np.arange(95.0, 100.0, 0.05)}
    )
)


@dataclass(frozen=True)
class PeriodScore:
    """Max score reached inside a case window (positive) or a control period (negative)."""

    period_id: str
    split: str
    max_score: float
    is_case: bool


@dataclass(frozen=True)
class ThresholdResult:
    threshold: float
    f1: float
    tp: int
    fp: int
    fn: int


class TestSplitLeakageError(ValueError):
    __test__ = False  # not a pytest class


def select_threshold(
    periods: list[PeriodScore], grid: tuple[float, ...] = DEFAULT_GRID
) -> ThresholdResult:
    leaked = [p.period_id for p in periods if p.split != "dev"]
    if leaked:
        raise TestSplitLeakageError(f"threshold tuning received non-dev periods: {leaked}")
    if not any(p.is_case for p in periods):
        raise ValueError("need at least one dev case to tune a threshold")

    best: ThresholdResult | None = None
    for t in sorted(grid):
        tp = sum(p.is_case and p.max_score >= t for p in periods)
        fn = sum(p.is_case and p.max_score < t for p in periods)
        fp = sum((not p.is_case) and p.max_score >= t for p in periods)
        f1 = 2 * tp / (2 * tp + fp + fn) if tp else 0.0
        # ">=" so ties go to the higher (more conservative) threshold
        if best is None or f1 >= best.f1:
            best = ThresholdResult(threshold=t, f1=round(f1, 4), tp=tp, fp=fp, fn=fn)
    assert best is not None
    return best
