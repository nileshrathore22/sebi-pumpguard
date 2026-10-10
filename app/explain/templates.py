"""Deterministic explanation used when no LLM is configured or the LLM output fails grounding."""

from typing import Any


def _fmt(v: float) -> str:
    return f"{v:g}"


def template_explanation(payload: dict[str, Any]) -> str:
    symbol, day = payload["symbol"], payload["as_of_date"]
    score, threshold = _fmt(payload["score"]), _fmt(payload["threshold"])
    if payload["flagged"]:
        head = (
            f"On {day}, {symbol} received an anomaly risk score of {score} out of 100, at or above "
            f"the alert threshold of {threshold}. Its price-volume behaviour was more unusual "
            f"than about {score}% of the reference trading days."
        )
    else:
        head = (
            f"On {day}, {symbol} received an anomaly risk score of {score} out of 100, below the "
            f"alert threshold of {threshold}. Its price-volume behaviour was within the usual range."
        )
    drivers = payload.get("top_features") or []
    if not drivers:
        return head
    parts = [
        f"{d['label']} was {_fmt(d['value'])} (a deviation of {_fmt(d['typical_deviation'])} "
        f"typical units from normal)"
        for d in drivers
    ]
    return head + " The main contributing factors were: " + "; ".join(parts) + "."
