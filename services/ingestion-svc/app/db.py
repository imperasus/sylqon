"""Engine/session wiring. ``create_all`` is the Phase 0 migration story —
the schema is additive-only for now; Alembic arrives when a breaking change does.
"""
from __future__ import annotations

import logging

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app import config
from app.models import Base

log = logging.getLogger(__name__)

_engine: Engine | None = None
_session_factory: sessionmaker | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(config.DATABASE_URL, pool_pre_ping=True)
    return _engine


def init_db(engine: Engine | None = None) -> Engine:
    engine = engine or get_engine()
    _migrate_computed_benchmarks(engine)
    Base.metadata.create_all(engine)
    _ensure_indexes(engine)
    return engine


def _ensure_indexes(engine: Engine) -> None:
    """Additive index migration: ``create_all`` never alters existing tables,
    so an index added to models.py after its table shipped must be created
    here. Existing names are read straight from the catalog — ``checkfirst``
    relies on reflection, and SQLite reflection skips expression-based indexes
    entirely, which would re-issue their CREATE INDEX on every startup. Plain
    CREATE INDEX blocks writes while it builds — on a large live table,
    pre-create the same index (same name) with CREATE INDEX CONCURRENTLY and
    this becomes a no-op."""
    from sqlalchemy import text

    if engine.dialect.name == "postgresql":
        q = text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
    else:  # sqlite
        q = text("SELECT name FROM sqlite_master WHERE type = 'index'")
    with engine.connect() as conn:
        existing = {row[0] for row in conn.execute(q)}
    for table in Base.metadata.tables.values():
        for index in table.indexes:
            if index.name not in existing:
                _create_index_idempotent(index, engine)


def _create_index_idempotent(index, engine: Engine) -> None:
    """The api and bot containers run init_db concurrently at deploy time —
    both can see the same index as missing and race the CREATE; the loser's
    duplicate error must not kill its startup."""
    from sqlalchemy.exc import DatabaseError

    try:
        index.create(engine)
    except DatabaseError as exc:
        message = str(exc).lower()
        if "already exists" not in message and "duplicate" not in message:
            raise
        log.info("index %s already created by a concurrent starter", index.name)


def _migrate_computed_benchmarks(engine: Engine) -> None:
    """The table gained a `band` PK column; it's a derived cache, so the old
    shape is simply dropped and recomputed on the next refresh."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "computed_benchmarks" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("computed_benchmarks")}
    if "band" not in columns:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE computed_benchmarks"))
    _ensure_columns(
        engine,
        "guild_configs",
        {
            "reports_channel_id": "BIGINT",
            "last_weekly_at": "TIMESTAMP WITH TIME ZONE"
            if engine.dialect.name == "postgresql" else "TIMESTAMP",
        },
    )


def _ensure_columns(engine: Engine, table: str, coldefs: dict[str, str]) -> None:
    """Additive column migration: ALTER TABLE ADD COLUMN for anything missing
    (create_all never alters existing tables)."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return  # create_all will build it with the full schema
    existing = {c["name"] for c in inspector.get_columns(table)}
    with engine.begin() as conn:
        for name, ddl in coldefs.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def get_session_factory(engine: Engine | None = None) -> sessionmaker:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=engine or get_engine(), expire_on_commit=False)
    return _session_factory


def open_session() -> Session:
    return get_session_factory()()
