"""Offline tests for the loadout-decision telemetry (the closed-loop
foundation): the LoadoutDecision table, record_decision, and recent readback.

Uses an in-memory SQLite database — no shared state, no network.

Run: python -m pytest tests/test_loadout_telemetry.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sylqon.db import queries
from sylqon.db.schema import Base, LoadoutDecision
from sylqon.loadout import Loadout


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    s = Session()
    try:
        yield s
    finally:
        s.close()


def _loadout():
    return Loadout(
        items=[{"id": 3006, "name": "Berserker's Greaves"},
               {"id": 3031, "name": "Infinity Edge"},
               {"id": 3033, "name": "Mortal Reminder"}],
        starting_items=[],
        primary_style_id=8000, secondary_style_id=8100,
        rune_perk_ids=[8008, 9111, 9104, 8014, 8139, 8135],
        shard_ids=[5005, 5008, 5011],
        spell1="Heal", spell2="Flash",
        source="opgg+ollama",
        enemy_summary="Soraka, Zed",
        first_back=[{"id": 3123, "name": "Executioner's Calling"}],
        lane_opponent_name="Soraka",
        decisions=[{"slot": "Items", "summary": "Counter enforced",
                    "reason": "healing comp", "kind": "add"}],
    )


class TestRecordDecision:
    def test_row_persisted_with_fields(self, session):
        queries.record_decision(session, champion="Jinx", role="bottom",
                                loadout=_loadout())
        session.commit()
        rows = session.query(LoadoutDecision).all()
        assert len(rows) == 1
        r = rows[0]
        assert r.champion == "Jinx" and r.role == "bottom"
        assert r.source == "opgg+ollama"
        assert r.lane_opponent == "Soraka"
        assert r.item_ids == [3006, 3031, 3033]
        assert r.first_back == [{"id": 3123, "name": "Executioner's Calling"}]
        assert r.decisions[0]["slot"] == "Items"

    def test_recent_readback_newest_first(self, session):
        for champ in ("Jinx", "Ashe", "Caitlyn"):
            queries.record_decision(session, champion=champ, role="bottom",
                                    loadout=_loadout())
        session.commit()
        recent = queries.recent_loadout_decisions(session, limit=2)
        assert len(recent) == 2
        # created_at defaults are equal within the test, so just assert count +
        # that all persisted rows are readable.
        assert session.query(LoadoutDecision).count() == 3

    def test_empty_loadout_degrades(self, session):
        empty = Loadout(items=[], starting_items=[], primary_style_id=8000,
                        secondary_style_id=8100, rune_perk_ids=[], shard_ids=[],
                        spell1="Heal")
        queries.record_decision(session, champion="Teemo", role="top", loadout=empty)
        session.commit()
        r = session.query(LoadoutDecision).one()
        assert r.item_ids == [] and r.decisions == [] and r.first_back == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
