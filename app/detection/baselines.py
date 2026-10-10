"""Baselines the IsolationForest must beat to justify its complexity."""

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import StandardScaler

from app.detection.base import EmpiricalNormaliser
from app.features.engineering import FEATURE_COLUMNS


class ZScoreRuleDetector:
    """Classic surveillance rule: flag unusually high volume vs the trailing 20-day baseline.

    Raw value = `vol_z20`; normalised to 0-100 with the same empirical CDF as the primary model.
    """

    name = "zscore_rule"

    def __init__(self, column: str = "vol_z20") -> None:
        self.column = column
        self.normaliser = EmpiricalNormaliser()

    def fit(self, features: pd.DataFrame, labels: np.ndarray | None = None) -> "ZScoreRuleDetector":
        self.normaliser.fit(features[self.column].to_numpy())
        return self

    def score(self, features: pd.DataFrame) -> np.ndarray:
        return self.normaliser.transform(features[self.column].to_numpy())


class LogisticBaseline:
    """Supervised baseline trained on dev-split labels only (1 = inside a dev case window)."""

    name = "logistic_regression"

    def __init__(self, random_state: int = 42) -> None:
        self.model: Pipeline = make_pipeline(
            StandardScaler(),
            LogisticRegression(class_weight="balanced", max_iter=2000, random_state=random_state),
        )

    def fit(self, features: pd.DataFrame, labels: np.ndarray | None = None) -> "LogisticBaseline":
        if labels is None or len(np.unique(labels)) < 2:
            raise ValueError("LogisticBaseline needs dev-split labels with both classes")
        self.model.fit(features[FEATURE_COLUMNS].to_numpy(), labels)
        return self

    def score(self, features: pd.DataFrame) -> np.ndarray:
        proba = self.model.predict_proba(features[FEATURE_COLUMNS].to_numpy())[:, 1]
        return np.round(100.0 * proba, 4)
