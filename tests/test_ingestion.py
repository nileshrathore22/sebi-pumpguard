from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import func, select

from app.db.models import PipelineRun, PriceHistory
from app.ingestion.fetchers import SyntheticFetcher, YahooFetcher, normalise_frame, yahoo_ticker
from app.ingestion.pipeline import run_ingestion
from app.ingestion.retry import retry_with_backoff
from app.ingestion.universe import load_universe


def _frame(n: int = 5) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=n)
    return pd.DataFrame(
        {"Date": dates, "Open": 10.0, "High": 11.0, "Low": 9.0, "Close": 10.5, "Volume": 1000}
    )


class MockFetcher:
    """Stands in for yfinance: returns canned frames, can fail N times or forever."""

    def __init__(self, fail_times: dict[str, int] | None = None) -> None:
        self.fail_times = dict(fail_times or {})
        self.calls: dict[str, int] = {}

    def fetch(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        self.calls[symbol] = self.calls.get(symbol, 0) + 1
        if self.fail_times.get(symbol, 0) > 0:
            self.fail_times[symbol] -= 1
            raise ConnectionError(f"boom {symbol}")
        return normalise_frame(_frame())


def _count(session) -> int:  # type: ignore[no-untyped-def]
    return session.scalar(select(func.count()).select_from(PriceHistory))


def test_ingestion_is_idempotent(session) -> None:  # type: ignore[no-untyped-def]
    fetcher = MockFetcher()
    run1 = run_ingestion(session, ["AAA", "BBB"], fetcher, sleep=lambda _: None)
    assert run1.status == "success"
    assert _count(session) == 10
    run2 = run_ingestion(session, ["AAA", "BBB"], fetcher, sleep=lambda _: None)
    assert run2.status == "success"
    assert _count(session) == 10  # re-run is a no-op


def test_retry_then_success(session) -> None:  # type: ignore[no-untyped-def]
    fetcher = MockFetcher(fail_times={"AAA": 2})
    run = run_ingestion(session, ["AAA"], fetcher, sleep=lambda _: None)
    assert run.status == "success"
    assert fetcher.calls["AAA"] == 3


def test_failure_isolated_per_symbol(session) -> None:  # type: ignore[no-untyped-def]
    fetcher = MockFetcher(fail_times={"BAD": 99})
    run = run_ingestion(session, ["GOOD", "BAD"], fetcher, attempts=3, sleep=lambda _: None)
    assert run.status == "partial"
    assert set(run.symbols_failed) == {"BAD"}
    assert _count(session) == 5
    stored = session.get(PipelineRun, run.run_id)
    assert stored.finished_at is not None


def test_all_failed_status(session) -> None:  # type: ignore[no-untyped-def]
    run = run_ingestion(session, ["X"], MockFetcher({"X": 99}), attempts=2, sleep=lambda _: None)
    assert run.status == "failed"


def test_retry_backoff_delays() -> None:
    delays: list[float] = []
    calls = {"n": 0}

    def flaky() -> int:
        calls["n"] += 1
        if calls["n"] < 4:
            raise RuntimeError("x")
        return 7

    assert retry_with_backoff(flaky, attempts=4, base_delay=1, sleep=delays.append) == 7
    assert delays == [1, 2, 4]

    def always_fails() -> int:
        raise RuntimeError("down")

    with pytest.raises(RuntimeError):
        retry_with_backoff(always_fails, attempts=2, sleep=delays.append)


def test_yahoo_fetcher_uses_ns_suffix(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    seen = {}

    class FakeTicker:
        def __init__(self, ticker: str) -> None:
            seen["ticker"] = ticker

        def history(self, **_: object) -> pd.DataFrame:
            return _frame(3).set_index("Date")

    import yfinance

    monkeypatch.setattr(yfinance, "Ticker", FakeTicker)
    df = YahooFetcher().fetch("SUZLON", date(2024, 1, 1), date(2024, 2, 1))
    assert seen["ticker"] == "SUZLON.NS"
    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume"]
    assert len(df) == 3
    assert yahoo_ticker("ABC.BO") == "ABC.BO"
    with pytest.raises(ValueError):
        YahooFetcher().fetch("SYNTH_01", date(2024, 1, 1), date(2024, 2, 1))


def test_synthetic_fetcher_window() -> None:
    df = SyntheticFetcher().fetch("SYNTH_01", date(2022, 1, 3), date(2022, 1, 31))
    assert df["date"].min() >= date(2022, 1, 3)
    assert df["date"].max() <= date(2022, 1, 31)


def test_universe_file_loads() -> None:
    symbols = load_universe(Path("config/universe.yaml"))
    assert 20 <= len(symbols) <= 30
    assert all(not s.endswith(".NS") for s in symbols)
