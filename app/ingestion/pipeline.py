"""Daily ingestion job with retries and per-symbol failure isolation."""

import time
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import PipelineRun
from app.ingestion.fetchers import PriceFetcher
from app.ingestion.loader import ensure_stocks, upsert_prices
from app.ingestion.retry import retry_with_backoff

log = get_logger(__name__)


def run_ingestion(
    session: Session,
    symbols: list[str],
    fetcher: PriceFetcher,
    *,
    start: date | None = None,
    end: date | None = None,
    attempts: int = 4,
    sleep: Callable[[float], None] | None = None,
) -> PipelineRun:
    end = end or date.today()
    start = start or end - timedelta(days=3 * 365)
    run = PipelineRun(
        run_id=uuid.uuid4().hex, started_at=datetime.now(UTC), status="running", symbols_failed={}
    )
    session.add(run)
    session.commit()

    ensure_stocks(session, symbols)
    session.commit()
    failed: dict[str, str] = {}
    inserted_total = 0
    for symbol in symbols:
        try:
            df = retry_with_backoff(
                lambda s=symbol: fetcher.fetch(s, start, end),  # type: ignore[misc]
                attempts=attempts,
                sleep=sleep or time.sleep,
            )
            inserted = upsert_prices(session, symbol, df)
            session.commit()
            inserted_total += inserted
            log.info("ingested symbol", extra={"symbol": symbol, "inserted": inserted})
        except Exception as exc:  # isolate failures: one bad symbol must not stop the run
            session.rollback()
            failed[symbol] = str(exc)[:500]
            log.error("symbol ingestion failed", extra={"symbol": symbol, "error": str(exc)})

    run.finished_at = datetime.now(UTC)
    run.symbols_failed = failed
    run.status = (
        "success" if not failed else ("failed" if len(failed) == len(symbols) else "partial")
    )
    session.commit()
    log.info(
        "ingestion finished",
        extra={"run_id": run.run_id, "status": run.status, "inserted": inserted_total},
    )
    return run
