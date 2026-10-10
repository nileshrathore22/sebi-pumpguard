from pathlib import Path

from app.core.constants import SYNTHETIC_PREFIX
from app.db.models import SebiCase
from app.ingestion.benchmark import (
    cases_from_db,
    load_benchmark,
    read_rows,
    store_cases,
    validate_rows,
)

TEMPLATE = Path("data/benchmark/cases_template.csv")
SYNTH = Path("data/benchmark/synthetic_cases.csv")


def _row(**kw: str) -> dict[str, str]:
    base = {
        "case_id": "C1",
        "symbol": "ABC",
        "window_start": "2020-01-01",
        "window_end": "2020-01-20",
        "order_reference": "WTM/XX/2021",
        "order_url": "https://www.sebi.gov.in/enforcement/orders/x.html",
        "description": "",
        "label": "pump_and_dump",
        "verified": "true",
        "split": "dev",
    }
    return base | kw


def test_template_has_no_verified_rows() -> None:
    rows = read_rows(TEMPLATE)
    assert rows, "template should contain placeholder rows"
    assert all(r["verified"].lower() == "false" for r in rows)


def test_template_rejected_in_official_mode() -> None:
    report = load_benchmark(TEMPLATE, "official")
    assert report.accepted == []
    assert any("verified" in w for w in report.warnings)


def test_unverified_allowed_only_in_dry_run() -> None:
    rows = [_row(verified="false")]
    assert validate_rows(rows, "official").accepted == []
    dry = validate_rows(rows, "dry-run")
    assert len(dry.accepted) == 1
    assert any("DRY-RUN" in w for w in dry.warnings)


def test_synthetic_never_official() -> None:
    report = validate_rows([_row(symbol="SYNTH_01", case_id="SYNTH_CASE_01")], "official")
    assert report.accepted == []


def test_validation_rules() -> None:
    rows = [
        _row(case_id="A", window_start="2020-02-01"),  # start > end
        _row(case_id="B", window_start="01/01/2020"),  # bad date
        _row(case_id="C", split="train"),
        _row(case_id="D", order_url="https://example.com"),
        _row(case_id="E", order_reference=""),
        _row(case_id="F"),
        _row(case_id="F"),
    ]
    report = validate_rows(rows, "official")
    assert [c.case_id for c in report.accepted] == ["F"]
    assert {cid for cid, _ in report.rejected} == {"A", "B", "C", "D", "E", "F"}
    assert "verified=1" in report.summary()


def test_chronology_warning() -> None:
    rows = [
        _row(case_id="D1", window_start="2021-01-01", window_end="2021-02-01"),
        _row(case_id="T1", split="test", window_start="2020-01-01", window_end="2020-01-10"),
    ]
    report = validate_rows(rows, "official")
    assert any("chronological" in w for w in report.warnings)


def test_synthetic_fixture_loads_dry_run() -> None:
    report = load_benchmark(SYNTH, "dry-run")
    assert len(report.accepted) == 12
    assert all(c.symbol.startswith(SYNTHETIC_PREFIX) for c in report.accepted)
    assert not any("chronological" in w for w in report.warnings)


def test_store_cases_idempotent(session) -> None:  # type: ignore[no-untyped-def]
    cases = load_benchmark(SYNTH, "dry-run").accepted
    store_cases(session, cases)
    store_cases(session, cases)
    assert session.query(SebiCase).count() == 12
    assert [c.case_id for c in cases_from_db(session)][0] == "SYNTH_CASE_01"
