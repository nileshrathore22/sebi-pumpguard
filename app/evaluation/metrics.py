"""Case-level classification metrics with stratified bootstrap confidence intervals."""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Confusion:
    tp: int
    fn: int
    fp: int
    tn: int


def confusion(case_hits: np.ndarray, control_hits: np.ndarray) -> Confusion:
    case_hits, control_hits = np.asarray(case_hits, bool), np.asarray(control_hits, bool)
    return Confusion(
        tp=int(case_hits.sum()),
        fn=int((~case_hits).sum()),
        fp=int(control_hits.sum()),
        tn=int((~control_hits).sum()),
    )


def _safe_div(a: float, b: float) -> float | None:
    return a / b if b else None


def metrics_from(c: Confusion) -> dict[str, float | None]:
    precision = _safe_div(c.tp, c.tp + c.fp)
    recall = _safe_div(c.tp, c.tp + c.fn)
    f1 = _safe_div(2 * c.tp, 2 * c.tp + c.fp + c.fn) if (c.tp + c.fp + c.fn) else None
    fpr = _safe_div(c.fp, c.fp + c.tn)
    return {"precision": precision, "recall": recall, "f1": f1, "false_positive_rate": fpr}


def bootstrap_ci(
    case_hits: np.ndarray,
    control_hits: np.ndarray,
    *,
    n_boot: int = 1000,
    seed: int = 42,
    alpha: float = 0.05,
) -> dict[str, tuple[float, float] | None]:
    """Resample cases and controls separately (stratified) with replacement."""
    rng = np.random.default_rng(seed)
    case_hits, control_hits = np.asarray(case_hits, bool), np.asarray(control_hits, bool)
    samples: dict[str, list[float]] = {
        k: [] for k in ("precision", "recall", "f1", "false_positive_rate")
    }
    for _ in range(n_boot):
        ch = rng.choice(case_hits, len(case_hits)) if len(case_hits) else case_hits
        co = rng.choice(control_hits, len(control_hits)) if len(control_hits) else control_hits
        for k, v in metrics_from(confusion(ch, co)).items():
            if v is not None:
                samples[k].append(v)
    out: dict[str, tuple[float, float] | None] = {}
    for k, vals in samples.items():
        if not vals:
            out[k] = None
            continue
        lo, hi = np.quantile(vals, [alpha / 2, 1 - alpha / 2])
        out[k] = (round(float(lo), 4), round(float(hi), 4))
    return out
