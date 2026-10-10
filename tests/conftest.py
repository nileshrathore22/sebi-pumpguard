from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import models  # noqa: F401
from app.db.base import Base
from app.ingestion.synthetic import SyntheticUniverse, generate_synthetic_universe


@pytest.fixture
def engine():  # type: ignore[no-untyped-def]
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine) -> Iterator[Session]:  # type: ignore[no-untyped-def]
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    yield s
    s.close()


@pytest.fixture(scope="session")
def synth() -> SyntheticUniverse:
    return generate_synthetic_universe(seed=42)
