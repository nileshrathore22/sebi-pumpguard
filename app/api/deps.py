from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from app.cache.redis_cache import Cache
from app.core.config import Settings, get_settings
from app.db.session import get_sessionmaker


def get_db() -> Iterator[Session]:
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()


def get_cache(request: Request) -> Cache:
    return request.app.state.cache


def settings_dep() -> Settings:
    return get_settings()
