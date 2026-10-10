from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.features.engineering import (
    FEATURE_COLUMNS,
    WARMUP_DAYS,
    compute_features,
    compute_universe_features,
)


def _mutate_future(df: pd.DataFrame, cut: date, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    out = df.copy()
    future = out["date"] > cut
    n = int(future.sum())
    out.loc[future, "volume"] = (out.loc[future, "volume"] * rng.uniform(0.1, 50, n)).astype(
        "int64"
    )
    factor = rng.uniform(0.3, 3.0, n)
    for col in ("open", "high", "low", "close"):
        out.loc[future, col] = out.loc[future, col] * factor
    return out


@pytest.mark.parametrize("cut_idx", [WARMUP_DAYS + 5, 200, 400, 650])
def test_no_lookahead_mutating_future_rows(synth, cut_idx: int) -> None:  # type: ignore[no-untyped-def]
    """Leakage guard: changing any row after date D must not change features at <= D."""
    for symbol in ("SYNTH_01", "SYNTH_15"):
        df = synth.prices[symbol]
        cut = df["date"].iloc[cut_idx]
        base = compute_features(df)
        mutated = compute_features(_mutate_future(df, cut, seed=cut_idx))
        past_base = base[base["date"] <= cut].reset_index(drop=True)
        past_mut = mutated[mutated["date"] <= cut].reset_index(drop=True)
        assert len(past_base) > 0
        pd.testing.assert_frame_equal(past_base, past_mut)
        # and the future really did change, so the test is not vacuous
        assert not base[base["date"] > cut][FEATURE_COLUMNS].equals(
            mutated[mutated["date"] > cut][FEATURE_COLUMNS].reset_index(drop=True)
        )


def test_truncated_history_gives_same_features(synth) -> None:  # type: ignore[no-untyped-def]
    df = synth.prices["SYNTH_03"]
    full = compute_features(df)
    cut = df["date"].iloc[300]
    truncated = compute_features(df[df["date"] <= cut])
    pd.testing.assert_frame_equal(full[full["date"] <= cut].reset_index(drop=True), truncated)


def test_warmup_and_no_nans(synth) -> None:  # type: ignore[no-untyped-def]
    df = synth.prices["SYNTH_02"]
    feats = compute_features(df)
    assert feats["date"].iloc[0] == df["date"].iloc[WARMUP_DAYS - 1]
    assert not feats[FEATURE_COLUMNS].isna().any().any()
    assert np.isfinite(feats[FEATURE_COLUMNS].to_numpy()).all()


def test_feature_values_simple_series() -> None:
    n = 80
    df = pd.DataFrame(
        {
            "date": [d.date() for d in pd.bdate_range("2024-01-01", periods=n)],
            "open": 100.0,
            "high": 101.0 + np.arange(n) % 2,
            "low": 99.0,
            "close": 100.0 * 1.01 ** np.arange(n),  # rises every day
            "volume": 1000 + (np.arange(n) % 3) * 10,
        }
    )
    df.loc[n - 1, "volume"] = 10_000
    feats = compute_features(df)
    last = feats.iloc[-1]
    assert last["consec_up_days"] == n - 1
    assert last["ret_1d"] == pytest.approx(0.01)
    assert last["ret_5d"] == pytest.approx(1.01**5 - 1)
    assert last["vol_z20"] > 10
    assert last["turnover_rel_median"] > 9


def test_universe_features(synth) -> None:  # type: ignore[no-untyped-def]
    subset = {k: synth.prices[k] for k in ("SYNTH_01", "SYNTH_13")}
    feats = compute_universe_features(subset)
    assert set(feats["symbol"]) == {"SYNTH_01", "SYNTH_13"}
    assert compute_universe_features({}).empty
