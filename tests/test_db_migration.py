"""Offline tests for the v2 SQLite migration.

Drives the migration functions against an in-memory SQLite database with a fake
catalog and a synthetic meta_cache dict — no network, no real DB file.

Run: python -m pytest tests/test_db_migration.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sylqon.data.catalog import Catalog
from sylqon.db.migrate import migrate_builds, seed_champions
from sylqon.db.schema import Base, Champion, ChampionBuild


class FakeCatalog(Catalog):
    """Catalog stub with a fixed champion table; no network/disk."""

    def __init__(self):  # bypass disk load
        self._data = {
            "fetched_at": 9e9,
            "patch": "99.1.1",
            "champions": {
                "103": {"name": "Ahri", "id": "Ahri", "tags": ["Mage"], "attack": 3, "magic": 8},
                "222": {"name": "Jinx", "id": "Jinx", "tags": ["Marksman"], "attack": 9, "magic": 4},
                "64": {"name": "Lee Sin", "id": "LeeSin", "tags": ["Fighter"], "attack": 8, "magic": 3},
            },
        }


def _sample_cache() -> dict:
    return {
        "patch": "99.1.1",
        "builds": {
            "Ahri|middle": {
                "source": "opgg",
                "build": {"items": [{"id": 3157, "name": "Zhonya's Hourglass"}],
                          "keystone": "Electrocute"},
            },
            "Jinx|bottom": {
                "source": "seed",
                "build": {"items": [{"id": 6672, "name": "Kraken Slayer"}],
                          "keystone": "Lethal Tempo"},
            },
            # Build for a champion not in the catalog: must be skipped gracefully.
            "Nonexistent|top": {"source": "opgg", "build": {"items": []}},
        },
    }


def _fresh_session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)()


def test_seed_champions_populates_rows():
    session = _fresh_session()
    catalog = FakeCatalog()
    n = seed_champions(session, catalog)
    session.commit()

    assert n == 3
    champs = session.query(Champion).all()
    assert {c.name for c in champs} == {"Ahri", "Jinx", "Lee Sin"}
    ahri = session.query(Champion).filter_by(name="Ahri").one()
    assert ahri.riot_key == 103
    assert ahri.slug == "Ahri"
    assert ahri.tags == ["Mage"]
    assert ahri.roles == []  # populated later from op.gg lane-meta


def test_migrate_builds_mirrors_cache():
    session = _fresh_session()
    catalog = FakeCatalog()
    seed_champions(session, catalog)
    n = migrate_builds(session, catalog, _sample_cache())
    session.commit()

    assert n == 2  # Ahri + Jinx; Nonexistent skipped
    ahri = session.query(Champion).filter_by(name="Ahri").one()
    build = session.query(ChampionBuild).filter_by(champion_id=ahri.id, role="middle").one()
    assert build.source == "opgg"
    assert build.patch == "99.1.1"
    assert build.build_json["keystone"] == "Electrocute"


def test_migration_is_idempotent():
    session = _fresh_session()
    catalog = FakeCatalog()
    cache = _sample_cache()

    seed_champions(session, catalog)
    migrate_builds(session, catalog, cache)
    session.commit()

    # Re-run: no duplicate rows, build_json refreshed in place.
    seed_champions(session, catalog)
    migrate_builds(session, catalog, cache)
    session.commit()

    assert session.query(Champion).count() == 3
    assert session.query(ChampionBuild).count() == 2


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
