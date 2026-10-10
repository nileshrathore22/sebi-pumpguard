"""ORM models. Mirrors section 5 of the spec; see docs/ARCHITECTURE.md for the ER diagram."""

import enum
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType


class CaseSplit(enum.StrEnum):
    DEV = "dev"
    TEST = "test"


class Stock(Base):
    __tablename__ = "stocks"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(255))
    exchange: Mapped[str] = mapped_column(String(16), default="NSE")
    sector: Mapped[str | None] = mapped_column(String(64))
    market_cap_band: Mapped[str | None] = mapped_column(String(16))


class PriceHistory(Base):
    __tablename__ = "price_history"
    __table_args__ = (
        UniqueConstraint("symbol", "date", name="uq_price_symbol_date"),
        Index("ix_price_symbol_date", "symbol", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(ForeignKey("stocks.symbol", ondelete="CASCADE"))
    date: Mapped[date] = mapped_column(Date)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(BigInteger)


class SebiCase(Base):
    __tablename__ = "sebi_cases"

    case_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str] = mapped_column(ForeignKey("stocks.symbol"))
    window_start: Mapped[date] = mapped_column(Date)
    window_end: Mapped[date] = mapped_column(Date)
    order_reference: Mapped[str | None] = mapped_column(String(255))
    order_url: Mapped[str | None] = mapped_column(String(1024))
    description: Mapped[str | None] = mapped_column(Text)
    label: Mapped[str] = mapped_column(String(32), default="pump_and_dump")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    split: Mapped[CaseSplit] = mapped_column(
        Enum(CaseSplit, name="case_split", values_callable=lambda e: [m.value for m in e])
    )


class AnomalyScore(Base):
    __tablename__ = "anomaly_scores"
    __table_args__ = (
        UniqueConstraint(
            "symbol", "as_of_date", "model_version", name="uq_score_symbol_date_model"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(ForeignKey("stocks.symbol", ondelete="CASCADE"))
    as_of_date: Mapped[date] = mapped_column(Date, index=True)
    score: Mapped[float] = mapped_column(Float)
    feature_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONType)
    model_version: Mapped[str] = mapped_column(String(64))


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(ForeignKey("stocks.symbol", ondelete="CASCADE"))
    triggered_at: Mapped[date] = mapped_column(Date)
    score: Mapped[float] = mapped_column(Float)
    explanation_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open")


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    symbols_failed: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
