import os
import sys
from pathlib import Path

import pytest

SERVICE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVICE_ROOT))


@pytest.fixture()
def factory():
    """Fresh in-memory SQLite session factory with the full schema — the
    shared DB fixture for read-view/aggregation tests."""
    from app.models import Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)

# Pin test-safe settings before app.config is imported anywhere.
os.environ.setdefault("RATELIMIT_MODE", "memory")
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("RIOT_API_KEY", "RGAPI-test-key")
os.environ.setdefault("CRAWL_ENABLED", "0")  # seed crawl is opt-in per test
