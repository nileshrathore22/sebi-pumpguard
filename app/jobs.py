"""Batch jobs shared by the CLI and the scheduler: ingest -> score -> alert."""

from datetime import date, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import get_logger
from app.db.models import Alert, AnomalyScore, PipelineRun
from app.detection.base import FeatureProfile
from app.detection.isolation_forest import IsolationForestDetector
from app.detection.scoring import persist_scores, score_features
from app.explain.graph import explain
from app.explain.llm import get_llm_client
from app.explain.payload import build_payload
from app.features.engineering import compute_universe_features
from app.ingestion.benchmark import load_benchmark, store_cases
from app.ingestion.fetchers import PriceFetcher, SyntheticFetcher, YahooFetcher
from app.ingestion.loader import load_all_prices
from app.ingestion.pipeline import run_ingestion
from app.ingestion.synthetic import CLEAN_SYMBOLS, END, PUMPS, START
from app.ingestion.universe import load_universe

log = get_logger(__name__)


def current_threshold(settings: Settings) -> float:
    """Dev-tuned IsolationForest threshold from the latest backtest artifact, else the default."""
    import json

    for tag in ("official", "dry_run"):
        path = settings.artifacts_dir / f"backtest_{tag}.json"
        if path.exists():
            data = json.loads(path.read_text())
            for d in data.get("detectors", []):
                if d["detector"] == "isolation_forest":
                    return float(d["threshold"])
    return settings.default_alert_threshold


def ingest(session: Session, settings: Settings) -> PipelineRun:
    fetcher: PriceFetcher
    if settings.data_source == "synthetic":
        symbols = [p.symbol for p in PUMPS] + list(CLEAN_SYMBOLS)
        return run_ingestion(session, symbols, SyntheticFetcher(), start=START, end=END)
    fetcher = YahooFetcher()
    return run_ingestion(session, load_universe(settings.universe_path), fetcher)


def score_and_alert(session: Session, settings: Settings, recent_days: int = 30) -> dict[str, Any]:
    """Fit the live model on all history, persist scores, and raise alerts on recent days."""
    prices = load_all_prices(session)
    features = compute_universe_features(prices)
    if features.empty:
        return {"scored": 0, "alerts": 0}
    detector = IsolationForestDetector().fit(features)
    profile = FeatureProfile.fit(features)
    scored = score_features(features, detector, profile)
    n = persist_scores(session, scored, settings.model_version)

    threshold = current_threshold(settings)
    llm = get_llm_client(settings)
    latest = scored["date"].max()
    recent = scored[
        (scored["score"] >= threshold) & (scored["date"] > latest - timedelta(days=recent_days))
    ]
    session.execute(delete(Alert).where(Alert.triggered_at > latest - timedelta(days=recent_days)))
    for _, row in recent.iterrows():
        payload = build_payload(
            symbol=row["symbol"],
            as_of_date=row["date"].isoformat(),
            score=row["score"],
            threshold=threshold,
            top_features=row["top_features"],
            model_version=settings.model_version,
        )
        session.add(
            Alert(
                symbol=row["symbol"],
                triggered_at=row["date"],
                score=float(row["score"]),
                explanation_text=explain(payload, llm)["text"],
                status="open",
            )
        )
    session.commit()
    log.info("scoring finished", extra={"scored": n, "alerts": len(recent), "threshold": threshold})
    return {
        "scored": n,
        "alerts": len(recent),
        "threshold": threshold,
        "latest_date": latest.isoformat(),
    }


def seed_demo(session: Session, settings: Settings) -> dict[str, Any]:
    """Load the synthetic universe + SYNTH_ cases, run the dry-run backtest, score everything."""
    from app.evaluation.backtest import BacktestConfig, run_backtest
    from app.evaluation.report import write_artifacts

    run = ingest(session, settings.model_copy(update={"data_source": "synthetic"}))
    cases = load_benchmark(settings.synthetic_cases_path, "dry-run").accepted
    store_cases(session, cases)
    result = run_backtest(load_all_prices(session), cases, BacktestConfig(mode="dry-run"))
    write_artifacts(result, settings.artifacts_dir)
    summary = score_and_alert(session, settings)
    return {"ingestion": run.status, "cases": len(cases)} | summary


def latest_score_date(session: Session, symbol: str, model_version: str) -> date | None:
    return session.scalar(
        select(AnomalyScore.as_of_date)
        .where(AnomalyScore.symbol == symbol, AnomalyScore.model_version == model_version)
        .order_by(AnomalyScore.as_of_date.desc())
        .limit(1)
    )
