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
    _migrate_computed_benchmarks(engine)
    Base.metadata.create_all(engine)
    return engine


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
