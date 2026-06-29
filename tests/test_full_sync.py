"""Offline coverage for the automated op.gg -> SQLite full sync.

Drives ``run_full_sync`` against an in-memory SQLite database with a fake catalog
and fully mocked op.gg HTTP fetchers — no network, no real DB file. Asserts that
converted builds land in BOTH the scoring DB (``ChampionBuild``) and the live
injection cache (``MetaCache``), which is what makes the "X BUILDS" badge reflect
the whole synced universe.

Run: python -m pytest tests/test_full_sync.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sylqon.cache.store import MetaCache
from sylqon.data.catalog import Catalog
from sylqon.db.schema import Base, ChampionBuild


class FakeCatalog(Catalog):
    """Catalog stub with a fixed champion table; no network/disk."""

    def __init__(self):  # bypass disk load
        self._data = {
            "fetched_at": 9e9,  # far future -> refresh_if_stale is a no-op
            "patch": "99.1.1",
            "champions": {
                "103": {"name": "Ahri", "id": "Ahri", "tags": ["Mage"], "attack": 3, "magic": 8},
                "222": {"name": "Jinx", "id": "Jinx", "tags": ["Marksman"], "attack": 9, "magic": 4},
            },
        }


def _fresh_session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)()


def test_run_full_sync_mirrors_into_db_and_cache(monkeypatch, tmp_path):
    import sylqon.cache.opgg as opgg_mod
    import sylqon.db.session as dbsess
    import sylqon.mcp.opgg_http as http
    import sylqon.mcp.sync as sync_mod

    # Shared in-memory DB session (sync imports these inside the function).
    session = _fresh_session()
    monkeypatch.setattr(dbsess, "init_db", lambda: None)
    monkeypatch.setattr(dbsess, "get_session", lambda: session)

    # Mock the op.gg network: two champions, one role each.
    monkeypatch.setattr(http, "fetch_all_meta", lambda region=None: {
        103: [{"role": "middle", "tier": 1, "win_rate": 0.52, "pick_rate": 0.1}],
        222: [{"role": "bottom", "tier": 2, "win_rate": 0.50, "pick_rate": 0.2}],
    })
    monkeypatch.setattr(http, "fetch_detail",
                        lambda cid, role, region=None: ({"champion": cid, "role": role}, []))
    monkeypatch.setattr(http, "fetch_synergies", lambda cid, role, region=None: [])

    # FakeCatalog has no items, so stub the conversion to a deterministic build.
    monkeypatch.setattr(opgg_mod, "opgg_to_build", lambda payload, catalog: {
        "items": [{"id": 3157, "name": "Zhonya's Hourglass"}], "keystone": "Electrocute",
    })

    # Live cache backed by a throwaway file.
    monkeypatch.setattr("sylqon.config.META_CACHE_PATH", tmp_path / "meta_cache.json")
    store = MetaCache()

    result = sync_mod.run_full_sync(store=store, catalog=FakeCatalog(), sleep=0)

    assert result["builds"] == 2
    assert result["cached"] == 2
    # Mirrored into the scoring DB...
    assert session.query(ChampionBuild).count() == 2
    # ...AND the live injection cache (this is what the badge counts).
    assert store.stats()["builds"] == 2
    assert store.get_build("Ahri", "middle", "99.1.1")[1] == "cache"


def test_run_full_sync_without_store_is_db_only(monkeypatch, tmp_path):
    """The CLI path passes no store: DB is populated, the live cache untouched."""
    import sylqon.cache.opgg as opgg_mod
    import sylqon.db.session as dbsess
    import sylqon.mcp.opgg_http as http
    import sylqon.mcp.sync as sync_mod

    session = _fresh_session()
    monkeypatch.setattr(dbsess, "init_db", lambda: None)
    monkeypatch.setattr(dbsess, "get_session", lambda: session)
    monkeypatch.setattr(http, "fetch_all_meta", lambda region=None: {
        103: [{"role": "middle", "tier": 1, "win_rate": 0.52, "pick_rate": 0.1}],
    })
    monkeypatch.setattr(http, "fetch_detail",
                        lambda cid, role, region=None: ({"champion": cid, "role": role}, []))
    monkeypatch.setattr(http, "fetch_synergies", lambda cid, role, region=None: [])
    monkeypatch.setattr(opgg_mod, "opgg_to_build", lambda payload, catalog: {
        "items": [{"id": 3157, "name": "Zhonya's Hourglass"}], "keystone": "Electrocute",
    })

    result = sync_mod.run_full_sync(catalog=FakeCatalog(), sleep=0)

    assert result["builds"] == 1
    assert result["cached"] == 0  # no store -> nothing pre-warmed
    assert session.query(ChampionBuild).count() == 1


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
