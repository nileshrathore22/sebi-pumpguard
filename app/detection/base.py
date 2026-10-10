"""Shared detector interface and helpers."""

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pandas as pd

from app.features.engineering import FEATURE_COLUMNS


class Detector(Protocol):
    name: str

    def fit(self, features: pd.DataFrame, labels: np.ndarray | None = None) -> "Detector": ...

    def score(self, features: pd.DataFrame) -> np.ndarray:
        """Return a 0-100 anomaly risk score per row (higher = more unusual)."""
        ...


class EmpiricalNormaliser:
    """Maps a raw anomaly value to 0-100 = % of training days with a raw value <= it.

    A score of 99 therefore reads as "more unusual than 99% of the reference days", which is
    easy to explain and comparable across models with different raw scales.
    """

    def fit(self, raw: np.ndarray) -> "EmpiricalNormaliser":
        self._sorted = np.sort(np.asarray(raw, dtype=float))
        return self

    def transform(self, raw: np.ndarray) -> np.ndarray:
        ranks = np.searchsorted(self._sorted, np.asarray(raw, dtype=float), side="right")
        return np.round(100.0 * ranks / len(self._sorted), 4)


@dataclass
class FeatureProfile:
    """Robust per-feature reference (median / IQR) used to name the top contributing features."""

    median: pd.Series
    scale: pd.Series

    @classmethod
    def fit(cls, features: pd.DataFrame) -> "FeatureProfile":
        x = features[FEATURE_COLUMNS]
        iqr = x.quantile(0.75) - x.quantile(0.25)
        return cls(median=x.median(), scale=(iqr / 1.349).replace(0, 1.0))

    def robust_z(self, features: pd.DataFrame) -> pd.DataFrame:
        return (features[FEATURE_COLUMNS] - self.median) / self.scale

    def top_features(
        self, features: pd.DataFrame, k: int = 3
    ) -> list[list[dict[str, float | str]]]:
        z = self.robust_z(features).to_numpy()
        values = features[FEATURE_COLUMNS].to_numpy()
        out = []
        for zi, vi in zip(z, values, strict=True):
            order = np.argsort(-np.abs(zi), kind="stable")[:k]
            out.append(
                [
                    {
                        "feature": FEATURE_COLUMNS[j],
                        "value": round(float(vi[j]), 4),
                        "robust_z": round(float(zi[j]), 2),
                    }
                    for j in order
                ]
            )
        return out
