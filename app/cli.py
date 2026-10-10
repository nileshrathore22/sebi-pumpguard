"""Command-line entrypoint: `python -m app.cli <command>`."""

import argparse
import sys

from app.core.config import get_settings
from app.core.logging import configure_logging


def cmd_validate_cases(args: argparse.Namespace) -> int:
    from app.ingestion.benchmark import load_benchmark

    path = args.path or get_settings().benchmark_path
    report = load_benchmark(path, args.mode)
    print(f"Validating {path}")
    print(report.summary())
    ok = (
        bool(report.accepted) and report.verified_count >= 15
        if args.mode == "official"
        else bool(report.accepted)
    )
    print("RESULT:", "ACCEPTABLE" if ok else "NOT YET ACCEPTABLE")
    return 0 if ok else 1


def load_backtest_inputs(source: str, mode: str):
    from app.ingestion.benchmark import cases_from_db, load_benchmark

    settings = get_settings()
    if source == "synthetic":
        from app.ingestion.synthetic import generate_synthetic_universe

        prices = generate_synthetic_universe().prices
        cases = load_benchmark(settings.synthetic_cases_path, "dry-run").accepted
        return prices, cases, None
    from app.db.models import Stock
    from app.db.session import get_sessionmaker
    from app.ingestion.benchmark import validate_rows
    from app.ingestion.loader import load_all_prices

    with get_sessionmaker()() as session:
        prices = load_all_prices(session)
        db_cases = cases_from_db(session)
        meta = {
            s.symbol: {"sector": s.sector, "market_cap_band": s.market_cap_band}
            for s in session.query(Stock).all()
        }
    if mode == "official":
        db_cases = [c for c in db_cases if c.verified and not c.is_synthetic]
    _ = validate_rows  # validation happens when cases are loaded into the DB
    return prices, db_cases, meta


def cmd_backtest(args: argparse.Namespace) -> int:
    from app.evaluation.backtest import BacktestConfig, run_backtest
    from app.evaluation.report import markdown_summary, update_evaluation_doc, write_artifacts

    if args.source == "synthetic" and args.mode == "official":
        print("ERROR: synthetic fixtures can never produce an official result", file=sys.stderr)
        return 2
    prices, cases, meta = load_backtest_inputs(args.source, args.mode)
    if not cases:
        print(
            "ERROR: no cases available for this mode. Fill data/benchmark/cases_template.csv and "
            "run `python -m app.cli load-cases`.",
            file=sys.stderr,
        )
        return 1
    result = run_backtest(
        prices, cases, BacktestConfig(mode=args.mode, n_bootstrap=args.bootstrap), meta
    )
    json_path, csv_path = write_artifacts(result, get_settings().artifacts_dir)
    if not args.no_doc:
        update_evaluation_doc(result)
    for w in result.warnings:
        print(f"WARNING: {w}")
    print(markdown_summary(result))
    print(f"\nArtifacts: {json_path} , {csv_path}")
    return 0


def cmd_seed_demo(args: argparse.Namespace) -> int:
    from sqlalchemy import func, select

    from app.db.models import Stock
    from app.db.session import get_sessionmaker
    from app.jobs import seed_demo

    with get_sessionmaker()() as session:
        if args.if_empty and session.scalar(select(func.count()).select_from(Stock)):
            print("database already has stocks; skipping demo seed")
            return 0
        print(seed_demo(session, get_settings()))
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    from app.db.session import get_sessionmaker
    from app.jobs import ingest

    with get_sessionmaker()() as session:
        run = ingest(session, get_settings())
        print(f"status={run.status} symbols_failed={run.symbols_failed}")
        return 0 if run.status != "failed" else 1


def cmd_score(args: argparse.Namespace) -> int:
    from app.db.session import get_sessionmaker
    from app.jobs import score_and_alert

    with get_sessionmaker()() as session:
        print(score_and_alert(session, get_settings()))
    return 0


def cmd_load_cases(args: argparse.Namespace) -> int:
    from app.db.session import get_sessionmaker
    from app.ingestion.benchmark import load_benchmark, store_cases

    path = args.path or get_settings().benchmark_path
    report = load_benchmark(path, args.mode)
    print(report.summary())
    if not report.accepted:
        return 1
    with get_sessionmaker()() as session:
        print(f"stored {store_cases(session, report.accepted)} cases")
    return 0


def cmd_schedule(args: argparse.Namespace) -> int:
    from app.scheduler import run

    run(run_now=args.run_now)
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_logging(get_settings().log_level)
    parser = argparse.ArgumentParser(prog="pumpguard")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate-cases", help="validate the SEBI benchmark CSV")
    p.add_argument("--path", type=__import__("pathlib").Path)
    p.add_argument("--mode", choices=["official", "dry-run"], default="official")
    p.set_defaults(func=cmd_validate_cases)

    p = sub.add_parser("backtest", help="run the retrospective backtest")
    p.add_argument("--source", choices=["synthetic", "db"], default="synthetic")
    p.add_argument("--mode", choices=["official", "dry-run"], default="dry-run")
    p.add_argument("--bootstrap", type=int, default=1000)
    p.add_argument("--no-doc", action="store_true", help="do not rewrite docs/EVALUATION.md")
    p.set_defaults(func=cmd_backtest)

    p = sub.add_parser("load-cases", help="validate and store benchmark cases in the DB")
    p.add_argument("--path", type=__import__("pathlib").Path)
    p.add_argument("--mode", choices=["official", "dry-run"], default="official")
    p.set_defaults(func=cmd_load_cases)

    for name, fn, help_ in (
        ("ingest", cmd_ingest, "ingest prices for the configured DATA_SOURCE"),
        ("score", cmd_score, "score all stored history and raise alerts"),
    ):
        sub.add_parser(name, help=help_).set_defaults(func=fn)

    p = sub.add_parser(
        "seed-demo", help="load synthetic demo data, backtest and score (no secrets)"
    )
    p.add_argument("--if-empty", action="store_true", help="skip if stocks already exist")
    p.set_defaults(func=cmd_seed_demo)

    p = sub.add_parser("schedule", help="run the daily ingest+score scheduler (blocking)")
    p.add_argument("--run-now", action="store_true")
    p.set_defaults(func=cmd_schedule)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
