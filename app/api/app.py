"""FastAPI application factory."""

from fastapi import FastAPI

from app.api.routers import health
from app.core.config import get_settings
from app.core.logging import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="PumpGuard API",
        version="0.1.0",
        description="Anomaly risk scores for NSE small/mid-cap price-volume behaviour. "
        "Not investment advice.",
    )
    app.include_router(health.router)
    return app
