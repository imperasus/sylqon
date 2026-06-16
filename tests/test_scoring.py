"""Offline tests for the 0-100 champion scorer (Phase 3).

In-memory SQLite seeded with champions, counters, synergies, meta tiers and
build win rates. Verifies component normalization and top-N ordering.

Run: python -m pytest tests/test_scoring.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sylqon.analysis.scoring import ChampionScorer
from sylqon.db import queries
from sylqon.db.schema import (
    Base,
    Champion,
    ChampionBuild,
    ChampionCounter,
    ChampionSynergy,
)


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)()


def _champ(session, name, key, role, tier=3, win_rate=50.0):
    c = Champion(name=name, riot_key=key, slug=name.replace(" ", ""),
                 roles=[role], op_gg_stats={role: {"tier": tier, "win_rate": win_rate}})
    session.add(c)
    session.flush()
    session.add(ChampionBuild(champion_id=c.id, role=role,
                              build_json={"items": []}, win_rate=win_rate))
    return c


def test_counter_score_normalization():
    """Port of the example: avg advantage of (+8, -6)/2 = +1 -> 55.0."""
    session = _session()
    me = _champ(session, "Vayne", 67, "bottom")
    e1 = _champ(session, "Malphite", 54, "top")
    e2 = _champ(session, "Zed", 238, "middle")
    session.add(ChampionCounter(champion_id=me.id, counter_id=e1.id, role="bottom",
                                advantage_score=8.0))
    session.add(ChampionCounter(champion_id=me.id, counter_id=e2.id, role="bottom",
                                advantage_score=-6.0))
    session.commit()

    scorer = ChampionScorer()
    score = scorer._counter_score(session, me.id, "bottom", [e1.id, e2.id])
    assert score == pytest.approx(55.0)


def test_no_enemies_or_allies_is_neutral():
    session = _session()
    me = _champ(session, "Jinx", 222, "bottom")
    session.commit()
    scorer = ChampionScorer()
    assert scorer._counter_score(session, me.id, "bottom", []) == 50.0
    assert scorer._synergy_score(session, me.id, "bottom", []) == 50.0


def test_meta_and_winrate_components():
    session = _session()
    op_champ = _champ(session, "Senna", 235, "bottom", tier=0, win_rate=55.0)
    session.commit()
    scorer = ChampionScorer()
    assert scorer._meta_score(op_champ, "bottom") == 100.0      # tier 0 = OP
    assert scorer._win_rate_score(session, op_champ.id, "bottom") == 100.0  # 55% -> 100


def test_top_recommendations_ordering():
    session = _session()
    # Strong: OP tier, high WR. Weak: low tier, low WR.
    _champ(session, "Senna", 235, "bottom", tier=0, win_rate=55.0)
    _champ(session, "Varus", 110, "bottom", tier=5, win_rate=47.0)
    _champ(session, "Ashe", 22, "bottom", tier=1, win_rate=50.0)
    # A champion in a different role must be excluded.
    _champ(session, "Garen", 86, "top", tier=0, win_rate=55.0)
    session.commit()

    recs = ChampionScorer().get_top_recommendations(session, "bottom", [], [], limit=5)
    names = [r["champion"]["name"] for r in recs]
    assert "Garen" not in names
    assert len(recs) == 3
    # Descending total score.
    totals = [r["score"]["total"] for r in recs]
    assert totals == sorted(totals, reverse=True)
    assert names[0] == "Senna"  # OP tier + high WR wins


def test_comfort_breaks_ties_toward_pool():
    """With identical draft value, the in-pool champion (comfort) ranks first."""
    session = _session()
    _champ(session, "Ashe", 22, "bottom", tier=2, win_rate=50.0)
    _champ(session, "Jhin", 202, "bottom", tier=2, win_rate=50.0)
    session.commit()
    recs = ChampionScorer().get_top_recommendations(
        session, "bottom", [], [], pool_names={"Jhin"}, limit=5)
    assert recs[0]["champion"]["name"] == "Jhin"
    jhin = next(r for r in recs if r["champion"]["name"] == "Jhin")
    assert jhin["in_pool"] is True
    assert jhin["score"]["comfort"] == 68.0  # in-pool baseline
    ashe = next(r for r in recs if r["champion"]["name"] == "Ashe")
    assert ashe["score"]["comfort"] == 42.0  # off-pool baseline


def test_dominant_counter_overrides_comfort():
    """An off-pool hard counter must outrank a comfortable in-pool pick."""
    session = _session()
    _champ(session, "Ashe", 22, "bottom", tier=3, win_rate=50.0)         # in pool, no counter
    off = _champ(session, "Draven", 119, "bottom", tier=3, win_rate=50.0)  # off pool, hard counter
    enemy = _champ(session, "Zed", 238, "middle", tier=2)
    session.add(ChampionCounter(champion_id=off.id, counter_id=enemy.id, role="bottom",
                                advantage_score=10.0))
    session.commit()
    recs = ChampionScorer().get_top_recommendations(
        session, "bottom", [], [enemy.id], pool_names={"Ashe"}, limit=5)
    assert recs[0]["champion"]["name"] == "Draven"
    assert recs[0]["in_pool"] is False


def test_personal_win_rate_lifts_comfort():
    """A strong personal win rate over a real sample beats the pool baseline."""
    session = _session()
    me = _champ(session, "Jinx", 222, "bottom")
    session.commit()
    scorer = ChampionScorer()
    hot = scorer._comfort_score("Jinx", {"Jinx"}, {"Jinx": {"games": 12, "win_rate": 0.62}})
    cold = scorer._comfort_score("Jinx", {"Jinx"}, {"Jinx": {"games": 1, "win_rate": 0.0}})
    assert hot >= 90          # 62% over 12 games → near-max comfort
    assert cold == 68.0       # tiny sample ignored → in-pool baseline


def test_ids_for_names_resolves_names_and_keys():
    session = _session()
    _champ(session, "Jinx", 222, "bottom")
    session.commit()
    assert queries.ids_for_names(session, ["Jinx"]) == queries.ids_for_names(session, [222])
    assert queries.ids_for_names(session, ["Nonexistent"]) == []


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
