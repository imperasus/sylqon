"""Engine/session wiring. ``create_all`` is the Phase 0 migration story —
the schema is additive-only for now; Alembic arrives when a breaking change does.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app import config
from app.models import Base

_engine: Engine | None = None
_session_factory: sessionmaker | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(config.DATABASE_URL, pool_pre_ping=True)
    return _engine


def init_db(engine: Engine | None = None) -> Engine:
    engine = engine or get_engine()
    Base.metadata.create_all(engine)
    return engine


def get_session_factory(engine: Engine | None = None) -> sessionmaker:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=engine or get_engine(), expire_on_commit=False)
    return _session_factory


def open_session() -> Session:
    return get_session_factory()()
