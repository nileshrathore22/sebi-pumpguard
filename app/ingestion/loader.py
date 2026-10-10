"""Idempotent writers: re-running with the same input never duplicates rows."""

from collections.abc import Iterable
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db.models import PriceHistory, Stock

CHUNK = 1000


def _insert(session: Session, model: Any) -> Any:
    dialect = session.get_bind().dialect.name
    return (pg_insert if dialect == "postgresql" else sqlite_insert)(model)


def ensure_stocks(session: Session, symbols: Iterable[str], **attrs: Any) -> None:
    existing = set(session.scalars(select(Stock.symbol)))
    for symbol in symbols:
        if symbol not in existing:
            session.add(Stock(symbol=symbol, exchange="NSE", **attrs))
    session.flush()


def upsert_prices(session: Session, symbol: str, df: pd.DataFrame) -> int:
    """Insert rows for (symbol, date) pairs not yet present. Returns rows inserted."""
    if df.empty:
        return 0
    records = [
        {
            "symbol": symbol,
            "date": r.date,
            "open": float(r.open),
            "high": float(r.high),
            "low": float(r.low),
            "close": float(r.close),
            "volume": int(r.volume),
        }
        for r in df.itertuples(index=False)
    ]
    inserted = 0
    for i in range(0, len(records), CHUNK):
        stmt = _insert(session, PriceHistory).values(records[i : i + CHUNK])
        stmt = stmt.on_conflict_do_nothing(index_elements=["symbol", "date"])
        result = session.execute(stmt)
        inserted += max(result.rowcount or 0, 0)  # type: ignore[attr-defined]
    return inserted


def load_prices(session: Session, symbol: str) -> pd.DataFrame:
    rows = session.execute(
        select(
            PriceHistory.date,
            PriceHistory.open,
            PriceHistory.high,
            PriceHistory.low,
            PriceHistory.close,
            PriceHistory.volume,
        )
        .where(PriceHistory.symbol == symbol)
        .order_by(PriceHistory.date)
    ).all()
    return pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])


def load_all_prices(session: Session) -> dict[str, pd.DataFrame]:
    symbols = session.scalars(select(Stock.symbol).order_by(Stock.symbol)).all()
    frames = {s: load_prices(session, s) for s in symbols}
    return {s: df for s, df in frames.items() if not df.empty}
