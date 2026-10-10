from app.detection.base import Detector
from app.detection.baselines import LogisticBaseline, ZScoreRuleDetector
from app.detection.isolation_forest import IsolationForestDetector

DETECTORS = ("isolation_forest", "zscore_rule", "logistic_regression")
SUPERVISED = {"logistic_regression"}


def build_detector(name: str) -> Detector:
    if name == "isolation_forest":
        return IsolationForestDetector()
    if name == "zscore_rule":
        return ZScoreRuleDetector()
    if name == "logistic_regression":
        return LogisticBaseline()
    raise ValueError(f"unknown detector {name!r}; choose from {DETECTORS}")
