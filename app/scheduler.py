"""Daily worker: ingest end-of-day prices, then score and raise alerts.

Runs after NSE close (15:30 IST) once Yahoo has published the day's bar.
"""

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import get_sessionmaker
from app.jobs import ingest, score_and_alert

log = get_logger(__name__)


def daily_job() -> None:
    settings = get_settings()
    with get_sessionmaker()() as session:
        run = ingest(session, settings)
        log.info(
            "daily ingestion",
            extra={"status": run.status, "failed": list(run.symbols_failed or {})},
        )
        if run.status != "failed":
            score_and_alert(session, settings)


def build_scheduler(hour: int = 18, minute: int = 30) -> BlockingScheduler:
    sched = BlockingScheduler(timezone="Asia/Kolkata")
    sched.add_job(
        daily_job,
        CronTrigger(day_of_week="mon-fri", hour=hour, minute=minute, timezone="Asia/Kolkata"),
        id="daily_ingest_score",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    return sched


def run(run_now: bool = False) -> None:
    if run_now:
        daily_job()
    sched = build_scheduler()
    log.info("scheduler started", extra={"jobs": [str(j.trigger) for j in sched.get_jobs()]})
    sched.start()
