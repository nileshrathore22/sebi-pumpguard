"""FastAPI application factory."""

import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.api.errors import register_error_handlers
from app.api.ratelimit import RateLimitMiddleware
from app.api.routers import cases, evaluate, health, stocks
from app.cache.redis_cache import Cache, MemoryCache, RedisCache
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger

log = get_logger(__name__)
WEB_INDEX = Path(__file__).resolve().parents[1] / "web" / "index.html"


def demo_seed() -> None:
    """Create tables and seed the synthetic demo if the DB is empty (single-container deploys)."""
    from sqlalchemy import func, select

    from app.db.base import Base
    from app.db.models import Stock
    from app.db.session import get_engine, get_sessionmaker
    from app.jobs import seed_demo

    try:
        Base.metadata.create_all(get_engine())
        with get_sessionmaker()() as session:
            if not session.scalar(select(func.count()).select_from(Stock)):
                log.info("seeding synthetic demo", extra=seed_demo(session, get_settings()))
    except Exception:
        log.exception("demo seed failed")


def build_cache(url: str) -> Cache:
    cache = RedisCache.from_url(url)
    if cache.ping():
        return cache
    log.warning("redis unreachable, using in-process cache", extra={"redis_url": url})
    return MemoryCache()


def create_app(cache: Cache | None = None) -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="PumpGuard API",
        version="0.1.0",
        description=(
            "Statistical anomaly risk scores for NSE small/mid-cap price-volume behaviour, "
            "validated retrospectively against SEBI enforcement cases. Scores are not "
            "accusations and not investment advice."
        ),
    )
    app.state.cache = cache or build_cache(settings.redis_url)
    app.add_middleware(RateLimitMiddleware, limit_per_minute=settings.rate_limit_per_minute)
    register_error_handlers(app)
    for r in (health, stocks, cases, evaluate):
        app.include_router(r.router)

    @app.get("/", include_in_schema=False)
    def web_ui() -> FileResponse:
        return FileResponse(WEB_INDEX)

    if settings.demo_seed_on_startup:
        threading.Thread(target=demo_seed, name="demo-seed", daemon=True).start()
    return app
