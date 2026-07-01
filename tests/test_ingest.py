"""Offline tests for the op.gg -> SQLite ingest (Phase 2).

In-memory SQLite, hand-seeded Champion rows; no network. Verifies the scale
mappings and the role/counter/synergy upserts (including idempotency and
unknown-champion handling).

Run: python -m pytest tests/test_ingest.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sylqon.db.schema import (
    Base,
    Champion,
    ChampionBuild,
    ChampionCounter,
    ChampionSynergy,
)
from sylqon.mcp import ingest

NAMES = ["Jinx", "Kalista", "Hwei", "Blitzcrank", "Thresh"]


def _session_with_champs():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True, expire_on_commit=False)()
    for i, name in enumerate(NAMES, start=1):
        session.add(Champion(name=name, riot_key=i, slug=name.replace(" ", ""), roles=[]))
    session.commit()
    return session


# -- mappings ----------------------------------------------------------------
def test_winrate_pct():
    assert ingest.winrate_pct(0.55) == 55.0


def test_advantage_from_winrate():
    assert ingest.advantage_from_winrate(0.5, True) == 0.0
    assert ingest.advantage_from_winrate(0.55, True) == 5.0
    assert ingest.advantage_from_winrate(0.59, False) == -9.0
    assert ingest.advantage_from_winrate(0.9, True) == 10.0  # clamped


def test_synergy_from_winrate():
    assert ingest.synergy_from_winrate(0.45) == 0.0
    assert ingest.synergy_from_winrate(0.50) == 5.0
    assert ingest.synergy_from_winrate(0.60) == 10.0  # clamped


def test_norm_role():
    assert ingest.norm_role("adc") == "bottom"
    assert ingest.norm_role("mid") == "middle"
    assert ingest.norm_role("support") == "utility"
    assert ingest.norm_role("top") == "top"


# -- lane meta ---------------------------------------------------------------
def test_ingest_lane_meta_sets_roles_and_stats():
    session = _session_with_champs()
    result = ingest.ingest_lane_meta(session, "adc", [
        {"champion": "Jinx", "tier": 1, "win_rate": 0.51, "pick_rate": 0.11},
        {"champion": "Ghost", "tier": 2, "win_rate": 0.5, "pick_rate": 0.0},  # unknown
    ])
    session.commit()

    assert result["role"] == "bottom"
    assert result["updated"] == 1
    assert result["unknown"] == ["Ghost"]
    jinx = session.query(Champion).filter_by(name="Jinx").one()
    assert jinx.roles == ["bottom"]
    assert jinx.op_gg_stats["bottom"] == {"tier": 1, "win_rate": 51.0, "pick_rate": 11.0}


def test_lane_meta_mirrors_winrate_onto_existing_build():
    session = _session_with_champs()
    jinx = session.query(Champion).filter_by(name="Jinx").one()
    session.add(ChampionBuild(champion_id=jinx.id, role="bottom", build_json={"items": []}))
    session.commit()

    ingest.ingest_lane_meta(session, "adc",
                            [{"champion": "Jinx", "tier": 1, "win_rate": 0.51, "pick_rate": 0.11}])
    session.commit()
    build = session.query(ChampionBuild).filter_by(champion_id=jinx.id, role="bottom").one()
    assert build.win_rate == 51.0
    assert build.pick_rate == 11.0


# -- counters ----------------------------------------------------------------
def test_ingest_counters_signs():
    session = _session_with_champs()
    result = ingest.ingest_counters(
        session, "Jinx", "adc",
        strong_counters=[{"champion_name": "Kalista", "win_rate": 0.59}],
        weak_counters=[{"champion_name": "Hwei", "win_rate": 0.57}],
    )
    session.commit()

    assert result["upserted"] == 2
    jinx = session.query(Champion).filter_by(name="Jinx").one()
    kalista = session.query(Champion).filter_by(name="Kalista").one()
    hwei = session.query(Champion).filter_by(name="Hwei").one()
    by_counter = {r.counter_id: r.advantage_score
                  for r in session.query(ChampionCounter).filter_by(champion_id=jinx.id).all()}
    assert by_counter[kalista.id] == -9.0   # countered by Kalista
    assert by_counter[hwei.id] == 7.0       # counters Hwei


def test_ingest_counters_idempotent_and_unknown_champion():
    session = _session_with_champs()
    payload = dict(champion="Jinx", position="adc",
                   strong_counters=[{"champion_name": "Kalista", "win_rate": 0.59}],
                   weak_counters=[])
    ingest.ingest_counters(session, **payload)
    ingest.ingest_counters(session, **payload)  # re-run
    session.commit()
    assert session.query(ChampionCounter).count() == 1

    bad = ingest.ingest_counters(session, "Ghost", "adc", [], [])
    assert "error" in bad


# -- synergies ---------------------------------------------------------------
def test_ingest_synergies():
    session = _session_with_champs()
    result = ingest.ingest_synergies(session, "Jinx", "adc", [
        {"synergy_champion_name": "Blitzcrank", "win_rate": 0.54},
        {"synergy_champion_name": "Thresh", "win_rate": 0.53},
    ])
    session.commit()
    assert result["upserted"] == 2
    jinx = session.query(Champion).filter_by(name="Jinx").one()
    blitz = session.query(Champion).filter_by(name="Blitzcrank").one()
    row = session.get(ChampionSynergy, (jinx.id, blitz.id, "bottom"))
    assert row.synergy_score == 9.0


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
