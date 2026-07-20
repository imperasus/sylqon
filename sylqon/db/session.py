"""Engine + session management for the SQLite store.

WAL journal mode lets the background scheduler write while the API reads without
lock contention (see architecture doc §9). Foreign keys are enforced explicitly
because SQLite leaves them off by default.
"""
from __future__ import annotations

import logging

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from sylqon import config
from sylqon.db.schema import Base

log = logging.getLogger(__name__)

engine: Engine = create_engine(f"sqlite:///{config.DB_PATH}", future=True)

# Additive columns introduced after a table first shipped. ``create_all`` only
# creates missing *tables*, never alters existing ones, so these are applied by
# hand (idempotent — skipped when the column already exists). SQLite ALTER TABLE
# ADD COLUMN is safe and non-locking for nullable columns.
_ADDITIVE_COLUMNS = [
    ("mission_runs", "champion_id", "INTEGER"),
    # F2 — matchup/pair sample size + patch for Wilson-style confidence weighting.
    ("champion_counters", "games", "INTEGER"),
    ("champion_counters", "patch", "VARCHAR"),
    ("champion_synergies", "games", "INTEGER"),
    ("champion_synergies", "patch", "VARCHAR"),
]


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _conn_record) -> None:  # pragma: no cover - trivial
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)


def init_db() -> None:
    """Create all tables if they do not exist, then apply additive column
    migrations. Safe to call repeatedly."""
    Base.metadata.create_all(engine)
    _apply_additive_columns()


def _apply_additive_columns() -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, column, coltype in _ADDITIVE_COLUMNS:
            if table not in existing_tables:
                continue  # create_all just made it with the column already present
            cols = {c["name"] for c in inspector.get_columns(table)}
            if column in cols:
                continue
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}"))
            log.info("Added column %s.%s", table, column)


def get_session() -> Session:
    """A new ORM session bound to the shared engine. Caller closes it."""
    return SessionLocal()
