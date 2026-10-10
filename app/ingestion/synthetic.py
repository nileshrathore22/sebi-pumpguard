"""Deterministic synthetic demo universe.

Everything here is SYNTHETIC and labelled with the `SYNTH_` prefix. It exists so the
pipeline, tests and dashboard run end to end without real SEBI cases. It is never
presented as real market data.

Each series is a geometric random walk with autocorrelated log-normal volume and
occasional one-day "news" spikes (realistic sources of false positives). Selected
symbols get an injected pump-and-dump: a quiet accumulation phase, a pump window with
rising price and elevated volume, then a dump.
"""

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from app.core.constants import SYNTHETIC_PREFIX

START = date(2021, 1, 1)
END = date(2023, 12, 29)


@dataclass(frozen=True)
class PumpSpec:
    symbol: str
    start: date
    length: int
    intensity: float  # 1.0 = typical; < 0.6 is deliberately subtle
    split: str


# Dev cases in 2022, test cases in 2023: a chronological split, so the threshold tuned on
# dev never sees anything from the test period.
PUMPS: tuple[PumpSpec, ...] = (
    PumpSpec("SYNTH_01", date(2022, 2, 14), 12, 1.2, "dev"),
    PumpSpec("SYNTH_02", date(2022, 4, 4), 10, 0.9, "dev"),
    PumpSpec("SYNTH_03", date(2022, 6, 6), 14, 1.0, "dev"),
    PumpSpec("SYNTH_04", date(2022, 8, 1), 9, 0.5, "dev"),
    PumpSpec("SYNTH_05", date(2022, 9, 19), 12, 1.4, "dev"),
    PumpSpec("SYNTH_06", date(2022, 11, 7), 11, 0.7, "dev"),
    PumpSpec("SYNTH_07", date(2023, 2, 6), 12, 1.1, "test"),
    PumpSpec("SYNTH_08", date(2023, 4, 10), 10, 0.8, "test"),
    PumpSpec("SYNTH_09", date(2023, 6, 5), 13, 1.3, "test"),
    PumpSpec("SYNTH_10", date(2023, 7, 24), 9, 0.45, "test"),
    PumpSpec("SYNTH_11", date(2023, 9, 11), 12, 1.0, "test"),
    PumpSpec("SYNTH_12", date(2023, 10, 30), 11, 0.75, "test"),
)
CLEAN_SYMBOLS = tuple(f"{SYNTHETIC_PREFIX}{i:02d}" for i in range(13, 21))


@dataclass
class SyntheticUniverse:
    prices: dict[str, pd.DataFrame]
    pumps: tuple[PumpSpec, ...] = field(default_factory=tuple)

    def case_rows(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for i, p in enumerate(self.pumps, start=1):
            dates = self.prices[p.symbol]["date"].tolist()
            start_idx = dates.index(p.start)
            rows.append(
                {
                    "case_id": f"SYNTH_CASE_{i:02d}",
                    "symbol": p.symbol,
                    "window_start": p.start.isoformat(),
                    "window_end": dates[start_idx + p.length - 1].isoformat(),
                    "order_reference": "SYNTHETIC - not a real SEBI order",
                    "order_url": "",
                    "description": f"Synthetic injected pump pattern (intensity {p.intensity})",
                    "label": "pump_and_dump",
                    "verified": False,
                    "split": p.split,
                }
            )
        return rows


def _base_series(rng: np.random.Generator, n: int) -> tuple[np.ndarray, np.ndarray]:
    returns = rng.normal(0.0002, 0.018, n)
    log_vol = np.empty(n)
    base = rng.uniform(11.5, 14.0)
    log_vol[0] = base
    for t in range(1, n):  # AR(1) volume around a symbol-specific base
        log_vol[t] = base + 0.6 * (log_vol[t - 1] - base) + rng.normal(0, 0.25)
    news = rng.random(n) < 0.01
    returns[news] += rng.choice([-1, 1], news.sum()) * rng.uniform(0.03, 0.06, news.sum())
    log_vol[news] += np.log(rng.uniform(2.5, 4.0, news.sum()))
    return returns, log_vol


def _inject_pump(returns: np.ndarray, log_vol: np.ndarray, start: int, spec: PumpSpec) -> None:
    k = spec.intensity
    accumulation = slice(max(start - 10, 0), start)
    log_vol[accumulation] += np.log(1 + 0.3 * k)
    for j in range(spec.length):
        ramp = (j + 1) / spec.length
        returns[start + j] += 0.035 * k * (1.2 - 0.4 * ramp)
        log_vol[start + j] += np.log(1 + 5.0 * k * (0.5 + ramp))
    dump_start = start + spec.length
    for j in range(6):
        returns[dump_start + j] -= 0.05 * k
        log_vol[dump_start + j] += np.log(1 + 3.0 * k)


def generate_synthetic_universe(seed: int = 42) -> SyntheticUniverse:
    dates = [d.date() for d in pd.bdate_range(START, END)]
    n = len(dates)
    pump_by_symbol = {p.symbol: p for p in PUMPS}
    prices: dict[str, pd.DataFrame] = {}
    for idx, symbol in enumerate([p.symbol for p in PUMPS] + list(CLEAN_SYMBOLS)):
        rng = np.random.default_rng(seed * 1000 + idx)
        returns, log_vol = _base_series(rng, n)
        if symbol in pump_by_symbol:
            spec = pump_by_symbol[symbol]
            _inject_pump(returns, log_vol, dates.index(spec.start), spec)
        close = rng.uniform(20, 300) * np.exp(np.cumsum(returns))
        open_ = close / np.exp(returns + rng.normal(0, 0.003, n))
        spread = np.abs(rng.normal(0, 0.012, n)) + np.abs(returns) / 2
        high = np.maximum(open_, close) * (1 + spread)
        low = np.minimum(open_, close) * (1 - spread)
        prices[symbol] = pd.DataFrame(
            {
                "date": dates,
                "open": open_.round(2),
                "high": high.round(2),
                "low": low.round(2),
                "close": close.round(2),
                "volume": np.exp(log_vol).astype("int64"),
            }
        )
    return SyntheticUniverse(prices=prices, pumps=PUMPS)
