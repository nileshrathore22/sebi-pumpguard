from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api.app import create_app
from app.api.deps import get_db
from app.cache.redis_cache import MemoryCache, RedisCache
from app.core.config import get_settings
from app.core.constants import DISCLAIMER
from app.jobs import seed_demo


@pytest.fixture(scope="module")
def seeded_engine(tmp_path_factory):  # type: ignore[no-untyped-def]
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    from app.db.base import Base

    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(eng)
    settings = get_settings().model_copy(update={"artifacts_dir": tmp_path_factory.mktemp("art")})
    with sessionmaker(bind=eng, expire_on_commit=False)() as s:
        summary = seed_demo(s, settings)
    assert summary["scored"] > 0
    return eng, settings


@pytest.fixture
def client(seeded_engine, monkeypatch) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    eng, settings = seeded_engine
    from app.core import config

    monkeypatch.setattr(config.get_settings(), "artifacts_dir", settings.artifacts_dir)
    app = create_app(cache=MemoryCache())
    maker = sessionmaker(bind=eng, expire_on_commit=False)

    def _db():  # type: ignore[no-untyped-def]
        s = maker()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _db
    yield TestClient(app)


def test_health(client) -> None:  # type: ignore[no-untyped-def]
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["database"] is True
    assert body["disclaimer"] == DISCLAIMER


def test_stocks_list(client) -> None:  # type: ignore[no-untyped-def]
    stocks = client.get("/stocks").json()["stocks"]
    assert len(stocks) == 20


def test_score_endpoint(client) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/stocks/SYNTH_09/score")
    assert r.status_code == 200
    body = r.json()
    assert 0 <= body["score"] <= 100
    assert body["explanation_path"] == "fallback"
    assert body["disclaimer"] == DISCLAIMER
    assert r.headers["X-PumpGuard-Disclaimer"] == DISCLAIMER
    assert len(body["top_features"]) == 3
    # cached second call returns identical body
    assert client.get("/stocks/SYNTH_09/score").json() == body


def test_score_as_of(client) -> None:  # type: ignore[no-untyped-def]
    body = client.get("/stocks/synth_09/score", params={"as_of": "2023-06-14"}).json()
    assert body["as_of_date"] <= "2023-06-14"


def test_score_unknown_symbol_error_format(client) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/stocks/NOPE/score")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == 404
    assert r.json()["disclaimer"] == DISCLAIMER


def test_validation_error_format(client) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/stocks/SYNTH_01/score", params={"as_of": "not-a-date"})
    assert r.status_code == 422
    assert "invalid request" in r.json()["error"]["message"]


def test_history(client) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/stocks/SYNTH_01/history", params={"start": "2022-01-01", "end": "2022-03-31"})
    pts = r.json()["points"]
    assert pts[0]["date"] >= "2022-01-01" and pts[-1]["date"] <= "2022-03-31"
    assert any(p["score"] is not None for p in pts)
    assert (
        client.get(
            "/stocks/SYNTH_01/history", params={"start": "2022-02-01", "end": "2022-01-01"}
        ).status_code
        == 400
    )
    assert client.get("/stocks/NOPE/history").status_code == 404


def test_cases(client) -> None:  # type: ignore[no-untyped-def]
    cases = client.get("/cases").json()["cases"]
    assert len(cases) == 12 and all(c["synthetic"] and not c["verified"] for c in cases)
    assert len(client.get("/cases", params={"split": "test"}).json()["cases"]) == 6
    assert client.get("/cases", params={"verified": True}).json()["cases"] == []


def test_replay(client) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/cases/SYNTH_CASE_09/replay")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "dry-run" and body["symbol"] == "SYNTH_09"
    assert len(body["series"]) > 20
    assert client.get("/cases/NOPE/replay").status_code == 404
    assert client.get("/cases/SYNTH_CASE_09/replay", params={"detector": "x"}).status_code == 422


def test_backtest_endpoint(client) -> None:  # type: ignore[no-untyped-def]
    r = client.post("/evaluate/backtest", json={"source": "synthetic", "n_bootstrap": 100})
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["mode"] == "dry-run"
    assert "periods" not in result["detectors"][0]
    bad = client.post("/evaluate/backtest", json={"source": "synthetic", "mode": "official"})
    assert bad.status_code == 400
    none = client.post("/evaluate/backtest", json={"source": "db", "mode": "official"})
    assert none.status_code == 409


def test_alerts(client) -> None:  # type: ignore[no-untyped-def]
    alerts = client.get("/alerts").json()["alerts"]
    assert all("manipulat" not in a["explanation_text"].lower() for a in alerts)


def test_rate_limit(seeded_engine, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.core import config

    monkeypatch.setattr(config.get_settings(), "rate_limit_per_minute", 3)
    app = create_app(cache=MemoryCache())
    maker = sessionmaker(bind=seeded_engine[0])

    def _db():  # type: ignore[no-untyped-def]
        with maker() as s:
            yield s

    app.dependency_overrides[get_db] = _db
    c = TestClient(app)
    codes = [c.get("/cases").status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3] == 429
    assert c.get("/cases").json()["error"]["code"] == 429
    assert c.get("/health").status_code == 200  # exempt


def test_redis_cache_roundtrip() -> None:
    import fakeredis

    cache = RedisCache(fakeredis.FakeRedis())
    assert cache.ping()
    cache.set_json("k", {"a": 1}, 10)
    assert cache.get_json("k") == {"a": 1}
    assert cache.get_json("missing") is None
    assert cache.incr_window("w", 60) == 1 and cache.incr_window("w", 60) == 2


def test_redis_down_degrades() -> None:
    cache = RedisCache.from_url("redis://127.0.0.1:1/0")
    assert not cache.ping()
    assert cache.get_json("k") is None
    cache.set_json("k", 1, 1)
    assert cache.incr_window("k", 1) == 0
