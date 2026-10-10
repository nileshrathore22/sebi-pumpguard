from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.db.models import AnomalyScore
from app.detection.base import EmpiricalNormaliser, FeatureProfile
from app.detection.baselines import LogisticBaseline, ZScoreRuleDetector
from app.detection.isolation_forest import IsolationForestDetector
from app.detection.registry import DETECTORS, build_detector
from app.detection.scoring import persist_scores, score_features
from app.detection.threshold import (
    DEFAULT_GRID,
    PeriodScore,
    TestSplitLeakageError,
    select_threshold,
)
from app.features.engineering import FEATURE_COLUMNS, compute_features, compute_universe_features
from app.ingestion.loader import ensure_stocks
from app.ingestion.synthetic import PUMPS

CUTOFF = date(2022, 12, 15)


@pytest.fixture(scope="module")
def feats(synth):  # type: ignore[no-untyped-def]
    return compute_universe_features(synth.prices)


@pytest.fixture(scope="module")
def iforest(feats):  # type: ignore[no-untyped-def]
    return IsolationForestDetector().fit(feats[feats["date"] < CUTOFF])


def _window(synth, feats, spec):  # type: ignore[no-untyped-def]
    dates = synth.prices[spec.symbol]["date"].tolist()
    end = dates[dates.index(spec.start) + spec.length - 1]
    f = feats[(feats["symbol"] == spec.symbol)]
    return f[(f["date"] >= spec.start) & (f["date"] <= end)]


def _flat_series(n: int = 400, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    return pd.DataFrame(
        {
            "date": [d.date() for d in pd.bdate_range("2022-01-03", periods=n)],
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": (200_000 * np.exp(rng.normal(0, 0.2, n))).astype("int64"),
        }
    )


def test_scoring_is_deterministic(feats) -> None:  # type: ignore[no-untyped-def]
    train = feats[feats["date"] < CUTOFF]
    a = IsolationForestDetector().fit(train).score(feats)
    b = IsolationForestDetector().fit(train).score(feats)
    np.testing.assert_array_equal(a, b)


def test_scores_in_range(iforest, feats) -> None:  # type: ignore[no-untyped-def]
    s = iforest.score(feats)
    assert s.min() >= 0 and s.max() <= 100


def test_synthetic_pumps_flagged(iforest, synth, feats) -> None:  # type: ignore[no-untyped-def]
    strong = [p for p in PUMPS if p.intensity >= 0.9]
    for spec in strong:
        assert iforest.score(_window(synth, feats, spec)).max() >= 99.5, spec.symbol


def test_flat_series_not_flagged(iforest) -> None:  # type: ignore[no-untyped-def]
    flat = compute_features(_flat_series())
    assert iforest.score(flat).max() < 99.5


def test_empirical_normaliser() -> None:
    n = EmpiricalNormaliser().fit(np.arange(100))
    np.testing.assert_allclose(n.transform(np.array([-1, 0, 49, 99, 1000])), [0, 1, 50, 100, 100])


def test_top_features_named(feats) -> None:  # type: ignore[no-untyped-def]
    profile = FeatureProfile.fit(feats)
    top = profile.top_features(feats.head(3), k=3)
    assert len(top) == 3 and len(top[0]) == 3
    assert all(t["feature"] in FEATURE_COLUMNS for t in top[0])
    assert abs(top[0][0]["robust_z"]) >= abs(top[0][1]["robust_z"])


def test_zscore_baseline(feats) -> None:  # type: ignore[no-untyped-def]
    s = ZScoreRuleDetector().fit(feats).score(feats)
    assert s.min() >= 0 and s.max() == 100


def test_logistic_requires_labels(feats) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError):
        LogisticBaseline().fit(feats, None)
    labels = (feats["vol_z20"] > 3).astype(int).to_numpy()
    s = LogisticBaseline().fit(feats, labels).score(feats)
    assert s.min() >= 0 and s.max() <= 100


def test_registry() -> None:
    for name in DETECTORS:
        assert build_detector(name).name == name
    with pytest.raises(ValueError):
        build_detector("nope")


def test_threshold_refuses_test_split() -> None:
    periods = [
        PeriodScore("dev_case", "dev", 99.0, True),
        PeriodScore("test_case", "test", 99.0, True),
    ]
    with pytest.raises(TestSplitLeakageError):
        select_threshold(periods)


def test_threshold_maximises_f1_prefers_higher_on_tie() -> None:
    periods = [
        PeriodScore("c1", "dev", 99.6, True),
        PeriodScore("c2", "dev", 99.2, True),
        PeriodScore("c3", "dev", 60.0, True),
        PeriodScore("n1", "dev", 99.0, False),
        PeriodScore("n2", "dev", 95.0, False),
    ]
    res = select_threshold(periods)
    assert (res.tp, res.fp, res.fn) == (2, 0, 1)
    assert res.threshold == max(t for t in DEFAULT_GRID if t <= 99.2)


def test_threshold_needs_cases() -> None:
    with pytest.raises(ValueError):
        select_threshold([PeriodScore("n", "dev", 50, False)])


def test_persist_scores_idempotent(session, iforest, feats) -> None:  # type: ignore[no-untyped-def]
    f = feats[feats["symbol"] == "SYNTH_01"].head(20)
    scored = score_features(f, iforest, FeatureProfile.fit(feats))
    ensure_stocks(session, ["SYNTH_01"])
    persist_scores(session, scored, "v-test")
    persist_scores(session, scored, "v-test")
    rows = session.query(AnomalyScore).all()
    assert len(rows) == 20
    assert set(rows[0].feature_snapshot) == {"features", "top_features"}
