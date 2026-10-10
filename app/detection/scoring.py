"""Turn features into persisted, auditable anomaly scores."""

from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.db.models import AnomalyScore
from app.detection.base import Detector, FeatureProfile
from app.features.engineering import FEATURE_COLUMNS
from app.ingestion.loader import _insert

CHUNK = 1000


def score_features(
    features: pd.DataFrame, detector: Detector, profile: FeatureProfile, top_k: int = 3
) -> pd.DataFrame:
    """Return features + `score` (0-100) + `top_features` (most deviating features)."""
    out = features.copy()
    out["score"] = detector.score(features) if len(features) else []
    out["top_features"] = profile.top_features(features, k=top_k) if len(features) else []
    return out


def snapshot(row: pd.Series) -> dict[str, Any]:
    return {
        "features": {c: round(float(row[c]), 6) for c in FEATURE_COLUMNS},
        "top_features": row["top_features"],
    }


def persist_scores(session: Session, scored: pd.DataFrame, model_version: str) -> int:
    """Upsert scores on (symbol, as_of_date, model_version); re-running is idempotent."""
    records = [
        {
            "symbol": row["symbol"],
            "as_of_date": row["date"],
            "score": float(row["score"]),
            "feature_snapshot": snapshot(row),
            "model_version": model_version,
        }
        for _, row in scored.iterrows()
    ]
    for i in range(0, len(records), CHUNK):
        stmt = _insert(session, AnomalyScore).values(records[i : i + CHUNK])
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "as_of_date", "model_version"],
            set_={"score": stmt.excluded.score, "feature_snapshot": stmt.excluded.feature_snapshot},
        )
        session.execute(stmt)
    session.commit()
    return len(records)
