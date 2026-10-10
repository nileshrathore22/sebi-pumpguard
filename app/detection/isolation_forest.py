"""Primary detector: a single IsolationForest pooled across symbols (see DECISIONS.md, D9)."""

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from app.detection.base import EmpiricalNormaliser
from app.features.engineering import FEATURE_COLUMNS


class IsolationForestDetector:
    name = "isolation_forest"

    def __init__(self, n_estimators: int = 300, max_samples: int = 256, random_state: int = 42):
        self.model = IsolationForest(
            n_estimators=n_estimators,
            max_samples=max_samples,
            contamination="auto",
            random_state=random_state,
            n_jobs=1,  # deterministic and CI-friendly
        )
        self.normaliser = EmpiricalNormaliser()

    def _raw(self, features: pd.DataFrame) -> np.ndarray:
        # sklearn: lower score_samples = more anomalous; flip so higher = more anomalous.
        return -self.model.score_samples(features[FEATURE_COLUMNS].to_numpy())

    def fit(
        self, features: pd.DataFrame, labels: np.ndarray | None = None
    ) -> "IsolationForestDetector":
        self.model.fit(features[FEATURE_COLUMNS].to_numpy())
        self.normaliser.fit(self._raw(features))
        return self

    def score(self, features: pd.DataFrame) -> np.ndarray:
        return self.normaliser.transform(self._raw(features))
