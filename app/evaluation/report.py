"""Write backtest artifacts (JSON + CSV) and the results section of docs/EVALUATION.md."""

import csv
import json
from dataclasses import asdict
from pathlib import Path

from app.core.config import ROOT_DIR
from app.evaluation.backtest import BacktestResult

START, END = "<!-- RESULTS:START -->", "<!-- RESULTS:END -->"


def _fmt(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.3f}"


def _ci(v: tuple[float, float] | None) -> str:
    return "n/a" if v is None else f"[{v[0]:.2f}, {v[1]:.2f}]"


def write_artifacts(result: BacktestResult, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = result.mode.replace("-", "_")
    json_path = out_dir / f"backtest_{tag}.json"
    csv_path = out_dir / f"backtest_{tag}_periods.csv"
    json_path.write_text(json.dumps(result.to_dict(), indent=2, default=str))
    rows = [
        asdict(p) | {"detector": d.detector, "threshold": d.threshold}
        for d in result.detectors
        for p in d.periods
    ]
    with csv_path.open("w", newline="") as fh:
        if rows:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    return json_path, csv_path


def markdown_summary(result: BacktestResult) -> str:
    lines = [
        f"### Latest backtest ({result.mode})",
        "",
    ]
    if result.mode == "dry-run":
        lines += [
            "> **DRY-RUN on synthetic `SYNTH_` fixtures. These numbers say nothing about real SEBI cases.**",
            "",
        ]
    lines += [
        f"- Model fit cutoff (no data on/after this date used for fitting): `{result.fit_cutoff}`",
        f"- Cases: dev={result.n_cases['dev']}, test={result.n_cases['test']}; "
        f"controls: dev={result.n_controls['dev']}, test={result.n_controls['test']}; "
        f"verified cases: {result.verified_cases}",
        "",
        "| Detector | Threshold (dev) | Dev F1 | Test precision | Test recall | Test F1 | Test FPR | Median lead (days) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for d in result.detectors:
        m, ci = d.test_metrics, d.test_ci
        lines.append(
            f"| `{d.detector}` | {d.threshold:.2f} | {d.dev_f1:.3f} "
            f"| {_fmt(m['precision'])} {_ci(ci['precision'])} "
            f"| {_fmt(m['recall'])} {_ci(ci['recall'])} "
            f"| {_fmt(m['f1'])} {_ci(ci['f1'])} "
            f"| {_fmt(m['false_positive_rate'])} {_ci(ci['false_positive_rate'])} "
            f"| {d.median_lead_time_days if d.median_lead_time_days is not None else 'n/a'} |"
        )
    lines += ["", "95% bootstrap confidence intervals in brackets (stratified, 1000 resamples)."]
    if result.warnings:
        lines += ["", "Warnings:"] + [f"- {w}" for w in result.warnings]
    return "\n".join(lines)


def update_evaluation_doc(
    result: BacktestResult, doc: Path = ROOT_DIR / "docs" / "EVALUATION.md"
) -> None:
    text = doc.read_text()
    if START not in text or END not in text:
        return
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    doc.write_text(f"{head}{START}\n{markdown_summary(result)}\n{END}{tail}")
