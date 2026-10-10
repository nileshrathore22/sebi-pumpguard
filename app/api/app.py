"""FastAPI application factory."""

from fastapi import FastAPI

from app.api.errors import register_error_handlers
from app.api.ratelimit import RateLimitMiddleware
from app.api.routers import cases, evaluate, health, stocks
from app.cache.redis_cache import Cache, MemoryCache, RedisCache
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger

log = get_logger(__name__)


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
    return app
