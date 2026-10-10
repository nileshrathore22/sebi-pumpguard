"""Negative controls: periods with no known enforcement action, used for false-positive rate.

For each case we pick up to `per_case` *other* symbols over the *same calendar dates*
(pre-window + window). A symbol qualifies only if none of its own cases overlap that period
(with a buffer). When stock metadata is available, symbols in the same sector / market-cap
band are preferred. Using the same dates keeps the control in the same split (and the same
market regime) as its case, so test controls are out-of-sample just like test cases.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from app.ingestion.benchmark import BenchmarkCase


@dataclass(frozen=True)
class ControlPeriod:
    control_id: str
    symbol: str
    window_start: date
    window_end: date
    split: str
    matched_case: str


def _overlaps(a0: date, a1: date, b0: date, b1: date) -> bool:
    return a0 <= b1 and b0 <= a1


def build_controls(
    cases: list[BenchmarkCase],
    available: dict[str, tuple[date, date]],
    *,
    per_case: int = 2,
    pre_window_days: int = 45,
    buffer_days: int = 60,
    metadata: dict[str, dict[str, str | None]] | None = None,
) -> list[ControlPeriod]:
    """`available` maps symbol -> (first date, last date) of its price history."""
    metadata = metadata or {}
    buffer = timedelta(days=buffer_days)
    controls: list[ControlPeriod] = []
    for idx, case in enumerate(sorted(cases, key=lambda c: c.case_id)):
        period_start = case.window_start - timedelta(days=pre_window_days)
        eligible = []
        for symbol, (first, last) in sorted(available.items()):
            if symbol == case.symbol or first > period_start or last < case.window_end:
                continue
            busy = any(
                c.symbol == symbol
                and _overlaps(
                    c.window_start - buffer, c.window_end + buffer, period_start, case.window_end
                )
                for c in cases
            )
            if not busy:
                eligible.append(symbol)
        case_meta = metadata.get(case.symbol, {})

        def similarity(sym: str, _m: dict[str, str | None] = case_meta) -> int:
            m = metadata.get(sym, {})
            return -sum(
                bool(_m.get(k)) and _m.get(k) == m.get(k) for k in ("sector", "market_cap_band")
            )

        # deterministic rotation so different cases use different controls
        rotated = (
            eligible[idx % len(eligible) :] + eligible[: idx % len(eligible)] if eligible else []
        )
        for symbol in sorted(rotated, key=similarity)[:per_case]:
            controls.append(
                ControlPeriod(
                    control_id=f"CTRL_{case.case_id}_{symbol}",
                    symbol=symbol,
                    window_start=case.window_start,
                    window_end=case.window_end,
                    split=case.split,
                    matched_case=case.case_id,
                )
            )
    return controls
