"""Structured payload handed to the explainer. Contains only PRE-COMPUTED, pre-rounded values;
the LLM never sees raw market data and never decides whether something is anomalous."""

from typing import Any

FEATURE_LABELS: dict[str, str] = {
    "vol_z20": "volume vs the previous 20 trading days (z-score)",
    "vol_z60": "volume vs the previous 60 trading days (z-score)",
    "ret_1d": "1-day price change (%)",
    "ret_3d": "3-day price change (%)",
    "ret_5d": "5-day price change (%)",
    "vp_divergence": "volume out of proportion to the price move (log ratio)",
    "range_expansion": "intraday range vs the 20-day average (x)",
    "volatility_ratio": "short-term vs medium-term volatility (x)",
    "turnover_rel_median": "traded value vs the 60-day median (x)",
    "consec_up_days": "consecutive up days",
}
PERCENT_FEATURES = {"ret_1d", "ret_3d", "ret_5d"}
REQUIRED_KEYS = ("symbol", "as_of_date", "score", "threshold", "flagged", "top_features")


def display_value(feature: str, value: float) -> float:
    if feature in PERCENT_FEATURES:
        return round(100 * value, 1)
    if feature == "consec_up_days":
        return float(int(value))
    return round(value, 1)


def build_payload(
    *,
    symbol: str,
    as_of_date: str,
    score: float,
    threshold: float,
    top_features: list[dict[str, Any]],
    model_version: str,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "as_of_date": as_of_date,
        "score": round(float(score), 1),
        "threshold": round(float(threshold), 1),
        "score_scale_max": 100,
        "flagged": bool(score >= threshold),
        "model_version": model_version,
        "top_features": [
            {
                "feature": t["feature"],
                "label": FEATURE_LABELS.get(str(t["feature"]), str(t["feature"])),
                "value": display_value(str(t["feature"]), float(t["value"])),
                "typical_deviation": round(float(t["robust_z"]), 1),
            }
            for t in top_features
        ],
    }
