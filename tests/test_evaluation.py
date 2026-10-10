import json
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from app.cli import main as cli_main
from app.evaluation.backtest import BacktestConfig, replay_case, run_backtest
from app.evaluation.controls import build_controls
from app.evaluation.metrics import bootstrap_ci, confusion, metrics_from
from app.evaluation.report import markdown_summary, update_evaluation_doc, write_artifacts
from app.ingestion.benchmark import load_benchmark

CFG = BacktestConfig(n_bootstrap=200)


@pytest.fixture(scope="module")
def cases():  # type: ignore[no-untyped-def]
    return load_benchmark(Path("data/benchmark/synthetic_cases.csv"), "dry-run").accepted


@pytest.fixture(scope="module")
def result(synth, cases):  # type: ignore[no-untyped-def]
    return run_backtest(synth.prices, cases, CFG)


def test_metrics_basic() -> None:
    c = confusion(np.array([1, 1, 0], bool), np.array([1, 0, 0, 0], bool))
    assert (c.tp, c.fn, c.fp, c.tn) == (2, 1, 1, 3)
    m = metrics_from(c)
    assert m["precision"] == pytest.approx(2 / 3)
    assert m["recall"] == pytest.approx(2 / 3)
    assert m["false_positive_rate"] == pytest.approx(0.25)
    assert metrics_from(confusion(np.array([], bool), np.array([], bool)))["f1"] is None


def test_bootstrap_ci_bounds() -> None:
    ci = bootstrap_ci(np.array([1, 1, 0, 1], bool), np.array([0, 0, 1, 0], bool), n_boot=300)
    lo, hi = ci["recall"]  # type: ignore[misc]
    assert 0 <= lo <= 0.75 <= hi <= 1
    assert bootstrap_ci(np.array([], bool), np.array([], bool), n_boot=10)["recall"] is None


def test_controls_never_overlap_cases(cases, synth) -> None:  # type: ignore[no-untyped-def]
    available = {s: (df["date"].min(), df["date"].max()) for s, df in synth.prices.items()}
    controls = build_controls(cases, available, per_case=2)
    assert len(controls) == 2 * len(cases)
    case_symbols = {c.case_id: c.symbol for c in cases}
    for k in controls:
        assert k.symbol != case_symbols[k.matched_case]
        for c in cases:
            if c.symbol == k.symbol:
                assert c.window_end + timedelta(days=60) < k.window_start - timedelta(days=45) or (
                    c.window_start - timedelta(days=60) > k.window_end
                )


def test_controls_prefer_same_sector(cases, synth) -> None:  # type: ignore[no-untyped-def]
    available = {s: (df["date"].min(), df["date"].max()) for s, df in synth.prices.items()}
    meta = {s: {"sector": "x" if s in {"SYNTH_01", "SYNTH_20"} else "y"} for s in synth.prices}
    first = [c for c in cases if c.symbol == "SYNTH_01"]
    controls = build_controls(first, available, per_case=1, metadata=meta)  # type: ignore[arg-type]
    assert controls[0].symbol == "SYNTH_20"


def test_backtest_end_to_end(result) -> None:  # type: ignore[no-untyped-def]
    assert result.n_cases == {"dev": 6, "test": 6}
    assert {d.detector for d in result.detectors} == {
        "isolation_forest",
        "zscore_rule",
        "logistic_regression",
    }
    for d in result.detectors:
        assert 50 <= d.threshold < 100
        assert set(d.test_metrics) == {"precision", "recall", "f1", "false_positive_rate"}
    iso = next(d for d in result.detectors if d.detector == "isolation_forest")
    assert iso.test_metrics["recall"] >= 0.5
    assert any("verified" in w for w in result.warnings)


def test_fit_cutoff_precedes_test_period(result, cases) -> None:  # type: ignore[no-untyped-def]
    cutoff = date.fromisoformat(result.fit_cutoff)
    for c in cases:
        if c.split == "test":
            assert cutoff <= c.window_start - timedelta(days=CFG.pre_window_days)


def test_threshold_unaffected_by_test_split_data(synth, cases, result) -> None:  # type: ignore[no-untyped-def]
    """Bias audit: wildly changing test-period data must not move any dev-tuned threshold."""
    cutoff = date.fromisoformat(result.fit_cutoff)
    mutated = {}
    for s, df in synth.prices.items():
        df = df.copy()
        after = df["date"] >= cutoff
        df.loc[after, "volume"] = df.loc[after, "volume"] * 40
        df.loc[after, "close"] = df.loc[after, "close"] * 3
        mutated[s] = df
    again = run_backtest(mutated, cases, CFG)
    assert [d.threshold for d in again.detectors] == [d.threshold for d in result.detectors]


def test_threshold_unaffected_by_test_labels(synth, cases, result) -> None:  # type: ignore[no-untyped-def]
    """Dropping or relabelling later test cases (keeping the earliest, which fixes the fit
    cutoff) must not move any threshold."""
    test = sorted((c for c in cases if c.split == "test"), key=lambda c: c.window_start)
    kept = [c for c in cases if c.split == "dev"] + test[:2]
    again = run_backtest(synth.prices, kept, CFG)
    assert again.fit_cutoff == result.fit_cutoff
    assert [d.threshold for d in again.detectors] == [d.threshold for d in result.detectors]


def test_backtest_requires_dev_case(synth, cases) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError):
        run_backtest(synth.prices, [c for c in cases if c.split == "test"], CFG)


def test_only_dev_cases_warns(synth, cases) -> None:  # type: ignore[no-untyped-def]
    res = run_backtest(
        synth.prices,
        [c for c in cases if c.split == "dev"],
        replace(CFG, detectors=("zscore_rule",)),
    )
    assert any("no test-split" in w for w in res.warnings)


def test_replay_case(synth, cases, result) -> None:  # type: ignore[no-untyped-def]
    replay = replay_case(synth.prices, cases, "SYNTH_CASE_09", result)
    assert replay["symbol"] == "SYNTH_09"
    assert replay["series"][0]["date"] < replay["window_start"]
    assert any(p["score"] is not None for p in replay["series"])
    with pytest.raises(KeyError):
        replay_case(synth.prices, cases, "NOPE", result)


def test_report_outputs(result, tmp_path) -> None:  # type: ignore[no-untyped-def]
    js, cs = write_artifacts(result, tmp_path)
    assert json.loads(js.read_text())["mode"] == "dry-run"
    assert cs.read_text().startswith("period_id")
    md = markdown_summary(result)
    assert "DRY-RUN" in md and "isolation_forest" in md
    doc = tmp_path / "EVAL.md"
    doc.write_text("intro\n<!-- RESULTS:START -->\nOLDCONTENT\n<!-- RESULTS:END -->\noutro\n")
    update_evaluation_doc(result, doc)
    text = doc.read_text()
    assert "OLDCONTENT" not in text and "outro" in text and "Latest backtest" in text


def test_cli_refuses_synthetic_official() -> None:
    assert cli_main(["backtest", "--source", "synthetic", "--mode", "official"]) == 2


def test_cli_validate_template_not_acceptable(capsys) -> None:  # type: ignore[no-untyped-def]
    assert cli_main(["validate-cases"]) == 1
    assert "NOT YET ACCEPTABLE" in capsys.readouterr().out
    assert (
        cli_main(
            ["validate-cases", "--path", "data/benchmark/synthetic_cases.csv", "--mode", "dry-run"]
        )
        == 0
    )


def test_cli_backtest_synthetic(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    from app.core import config

    monkeypatch.setattr(config.get_settings(), "artifacts_dir", tmp_path)
    assert cli_main(["backtest", "--bootstrap", "50", "--no-doc"]) == 0
    assert "WARNING" in capsys.readouterr().out
    assert (tmp_path / "backtest_dry_run.json").exists()
