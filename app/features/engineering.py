"""Strictly trailing feature engineering.

Every feature for date D is computed only from rows with date <= D. Baselines (means,
medians, standard deviations) are additionally shifted by one day so that day D is compared
against the *preceding* window, not against a window that already contains itself.
pandas `rolling` is trailing by default (`center=False`); we never use `center=True`,
`shift(-k)`, `bfill` or whole-series statistics. `tests/test_features.py` enforces this by
mutating future rows and asserting past features do not change.

All features are ratios, returns or z-scores relative to the symbol's own history, which
makes them comparable across symbols (see DECISIONS.md, D8).
"""

import numpy as np
import pandas as pd

FEATURE_COLUMNS: list[str] = [
    "vol_z20",
    "vol_z60",
    "ret_1d",
    "ret_3d",
    "ret_5d",
    "vp_divergence",
    "range_expansion",
    "volatility_ratio",
    "turnover_rel_median",
    "consec_up_days",
]
WARMUP_DAYS = 61  # 60-day baseline + 1-day shift


def _trailing_z(series: pd.Series, window: int) -> pd.Series:
    prev = series.shift(1)
    mean = prev.rolling(window, min_periods=window).mean()
    std = prev.rolling(window, min_periods=window).std()
    return (series - mean) / std.replace(0, np.nan)


def _consecutive_up(close: pd.Series) -> pd.Series:
    up = (close.diff() > 0).astype(int)
    run_id = (up == 0).cumsum()
    return up.groupby(run_id).cumsum().astype(float)


def compute_features(prices: pd.DataFrame) -> pd.DataFrame:
    """Return one row per date (after warm-up) with `date` and FEATURE_COLUMNS."""
    df = prices.sort_values("date").reset_index(drop=True)
    close, volume = df["close"].astype(float), df["volume"].astype(float)
    log_vol = np.log1p(volume)
    log_ret = np.log(close / close.shift(1))

    out = pd.DataFrame({"date": df["date"]})
    out["vol_z20"] = _trailing_z(log_vol, 20)
    out["vol_z60"] = _trailing_z(log_vol, 60)
    for k in (1, 3, 5):
        out[f"ret_{k}d"] = close / close.shift(k) - 1
    vol_median20 = volume.shift(1).rolling(20, min_periods=20).median()
    out["vp_divergence"] = np.log(volume / vol_median20) - np.log1p(100 * out["ret_1d"].abs())
    day_range = (df["high"] - df["low"]) / close
    out["range_expansion"] = day_range / day_range.shift(1).rolling(20, min_periods=20).mean()
    out["volatility_ratio"] = (
        log_ret.rolling(5, min_periods=5).std() / log_ret.rolling(60, min_periods=60).std()
    )
    turnover = close * volume
    out["turnover_rel_median"] = turnover / turnover.shift(1).rolling(60, min_periods=60).median()
    out["consec_up_days"] = _consecutive_up(close)

    out = out.replace([np.inf, -np.inf], np.nan)
    out = out.iloc[WARMUP_DAYS - 1 :].dropna(subset=FEATURE_COLUMNS)
    return out.reset_index(drop=True)


def compute_universe_features(prices: dict[str, pd.DataFrame]) -> pd.DataFrame:
    frames = []
    for symbol, df in prices.items():
        feats = compute_features(df)
        feats.insert(0, "symbol", symbol)
        frames.append(feats)
    if not frames:
        return pd.DataFrame(columns=["symbol", "date", *FEATURE_COLUMNS])
    return pd.concat(frames, ignore_index=True)
