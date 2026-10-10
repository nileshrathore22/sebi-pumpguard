from collections.abc import Iterator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.app import create_app
from app.api.deps import get_db
from app.cache.redis_cache import MemoryCache
from app.core.constants import DISCLAIMER


def _client(url: str) -> TestClient:
    eng = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    maker = sessionmaker(bind=eng)

    def _db() -> Iterator[Session]:
        with maker() as s:
            yield s

    app = create_app(cache=MemoryCache())
    app.dependency_overrides[get_db] = _db
    return TestClient(app)


def test_health_ok() -> None:
    resp = _client("sqlite://").get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok" and body["database"] and body["cache"]
    assert body["disclaimer"] == DISCLAIMER


def test_web_ui_served() -> None:
    resp = _client("sqlite://").get("/")
    assert resp.status_code == 200
    assert "PumpGuard" in resp.text and "text/html" in resp.headers["content-type"]
