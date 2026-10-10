"""Benchmark (SEBI case) loading and validation.

`official` mode accepts only complete rows with verified=true; `dry-run` mode also accepts
unverified rows (e.g. SYNTH_ fixtures) but every result is clearly marked as dry-run.
"""

import csv
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import MIN_VERIFIED_CASES, SYNTHETIC_PREFIX
from app.db.models import CaseSplit, SebiCase
from app.ingestion.loader import ensure_stocks

Mode = Literal["official", "dry-run"]
COLUMNS = [
    "case_id",
    "symbol",
    "window_start",
    "window_end",
    "order_reference",
    "order_url",
    "description",
    "label",
    "verified",
    "split",
]
REQUIRED = ["case_id", "symbol", "window_start", "window_end", "order_reference", "split"]


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    symbol: str
    window_start: date
    window_end: date
    order_reference: str
    order_url: str
    description: str
    label: str
    verified: bool
    split: str

    @property
    def is_synthetic(self) -> bool:
        return self.symbol.startswith(SYNTHETIC_PREFIX) or self.case_id.startswith(SYNTHETIC_PREFIX)


@dataclass
class ValidationReport:
    mode: Mode
    accepted: list[BenchmarkCase] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def verified_count(self) -> int:
        return sum(c.verified for c in self.accepted)

    def summary(self) -> str:
        lines = [
            f"mode={self.mode} accepted={len(self.accepted)} rejected={len(self.rejected)} "
            f"verified={self.verified_count}"
        ]
        lines += [f"  REJECTED {cid}: {why}" for cid, why in self.rejected]
        lines += [f"  WARNING {w}" for w in self.warnings]
        return "\n".join(lines)


def _parse_bool(v: str) -> bool:
    return str(v).strip().lower() in {"true", "1", "yes", "y"}


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        missing = set(COLUMNS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"benchmark file missing columns: {sorted(missing)}")
        return [{k: (v or "").strip() for k, v in row.items() if k} for row in reader]


def validate_rows(rows: list[dict[str, str]], mode: Mode) -> ValidationReport:
    report = ValidationReport(mode=mode)
    seen: set[str] = set()
    for i, row in enumerate(rows, start=2):
        cid = row.get("case_id") or f"<row {i}>"
        missing = [c for c in REQUIRED if not row.get(c)]
        if missing:
            report.rejected.append((cid, f"missing {', '.join(missing)}"))
            continue
        if cid in seen:
            report.rejected.append((cid, "duplicate case_id"))
            continue
        try:
            start, end = (
                date.fromisoformat(row["window_start"]),
                date.fromisoformat(row["window_end"]),
            )
        except ValueError:
            report.rejected.append((cid, "dates must be YYYY-MM-DD"))
            continue
        if start > end:
            report.rejected.append((cid, "window_start after window_end"))
            continue
        if row["split"] not in {"dev", "test"}:
            report.rejected.append((cid, "split must be 'dev' or 'test'"))
            continue
        case = BenchmarkCase(
            case_id=cid,
            symbol=row["symbol"].upper(),
            window_start=start,
            window_end=end,
            order_reference=row["order_reference"],
            order_url=row.get("order_url", ""),
            description=row.get("description", ""),
            label=row.get("label") or "pump_and_dump",
            verified=_parse_bool(row.get("verified", "false")),
            split=row["split"],
        )
        if mode == "official":
            if not case.verified:
                report.rejected.append((cid, "verified=false (allowed only in dry-run mode)"))
                continue
            if case.is_synthetic:
                report.rejected.append((cid, "synthetic cases are never allowed in official mode"))
                continue
            if "sebi.gov.in" not in case.order_url:
                report.rejected.append((cid, "order_url must link to the order on sebi.gov.in"))
                continue
        seen.add(cid)
        report.accepted.append(case)

    _check_chronology(report)
    if mode == "official" and report.verified_count < MIN_VERIFIED_CASES:
        report.warnings.append(
            f"only {report.verified_count} verified cases (< {MIN_VERIFIED_CASES}); "
            "metrics will have very wide confidence intervals"
        )
    if mode == "dry-run":
        report.warnings.append(
            "DRY-RUN: includes unverified/synthetic cases; not an official result"
        )
    return report


def _check_chronology(report: ValidationReport) -> None:
    dev = [c for c in report.accepted if c.split == "dev"]
    test = [c for c in report.accepted if c.split == "test"]
    if not dev or not test:
        if report.accepted:
            report.warnings.append("need at least one dev and one test case for threshold tuning")
        return
    latest_dev = max(c.window_end for c in dev)
    early = [c.case_id for c in test if c.window_start <= latest_dev]
    if early:
        report.warnings.append(
            f"test cases start before the last dev case ends ({', '.join(early)}); "
            "a chronological split (older=dev, newer=test) is recommended"
        )


def load_benchmark(path: Path, mode: Mode) -> ValidationReport:
    return validate_rows(read_rows(path), mode)


def store_cases(session: Session, cases: list[BenchmarkCase]) -> int:
    """Upsert cases into `sebi_cases` (idempotent on case_id)."""
    ensure_stocks(session, sorted({c.symbol for c in cases}))
    existing = set(session.scalars(select(SebiCase.case_id)))
    for c in cases:
        values = {
            "symbol": c.symbol,
            "window_start": c.window_start,
            "window_end": c.window_end,
            "order_reference": c.order_reference,
            "order_url": c.order_url or None,
            "description": c.description or None,
            "label": c.label,
            "verified": c.verified,
            "split": CaseSplit(c.split),
        }
        if c.case_id in existing:
            obj = session.get(SebiCase, c.case_id)
            for k, v in values.items():
                setattr(obj, k, v)
        else:
            session.add(SebiCase(case_id=c.case_id, **values))
    session.commit()
    return len(cases)


def cases_from_db(session: Session) -> list[BenchmarkCase]:
    return [
        BenchmarkCase(
            case_id=r.case_id,
            symbol=r.symbol,
            window_start=r.window_start,
            window_end=r.window_end,
            order_reference=r.order_reference or "",
            order_url=r.order_url or "",
            description=r.description or "",
            label=r.label,
            verified=r.verified,
            split=r.split.value,
        )
        for r in session.scalars(select(SebiCase).order_by(SebiCase.window_start))
    ]
