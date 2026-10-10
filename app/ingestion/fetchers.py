"""Market-data fetchers. Every fetcher returns a DataFrame with columns
date (datetime.date), open, high, low, close, volume, sorted by date."""

from datetime import date
from typing import Protocol

import pandas as pd

from app.core.constants import SYNTHETIC_PREFIX

PRICE_COLUMNS = ["date", "open", "high", "low", "close", "volume"]


class PriceFetcher(Protocol):
    def fetch(self, symbol: str, start: date, end: date) -> pd.DataFrame: ...


def normalise_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=PRICE_COLUMNS)
    out = df.copy()
    out.columns = [str(c).lower() for c in out.columns]
    if "date" not in out.columns:
        out = out.reset_index().rename(columns={"index": "date", "Date": "date"})
        out.columns = [str(c).lower() for c in out.columns]
    out["date"] = pd.to_datetime(out["date"]).dt.date
    out = out[PRICE_COLUMNS].dropna()
    out["volume"] = out["volume"].astype("int64")
    return out.sort_values("date").drop_duplicates("date").reset_index(drop=True)


def yahoo_ticker(symbol: str) -> str:
    return symbol if symbol.endswith((".NS", ".BO")) else f"{symbol}.NS"


class YahooFetcher:
    """NSE daily OHLCV via yfinance (symbols mapped to `SYMBOL.NS`)."""

    def fetch(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        import yfinance as yf

        if symbol.startswith(SYNTHETIC_PREFIX):
            raise ValueError(f"{symbol} is synthetic; use SyntheticFetcher")
        raw = yf.Ticker(yahoo_ticker(symbol)).history(
            start=start.isoformat(), end=end.isoformat(), interval="1d", auto_adjust=False
        )
        if raw is None or raw.empty:
            raise ValueError(f"no data returned for {symbol}")
        raw = raw.reset_index()
        raw["Date"] = pd.to_datetime(raw["Date"]).dt.tz_localize(None)
        return normalise_frame(raw)


class SyntheticFetcher:
    """Serves the deterministic SYNTH_ demo universe (see app.ingestion.synthetic)."""

    def __init__(self, seed: int = 42) -> None:
        from app.ingestion.synthetic import generate_synthetic_universe

        self._data = generate_synthetic_universe(seed=seed).prices

    def fetch(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        if symbol not in self._data:
            raise KeyError(f"unknown synthetic symbol {symbol}")
        df = self._data[symbol]
        return df[(df["date"] >= start) & (df["date"] <= end)].reset_index(drop=True)
