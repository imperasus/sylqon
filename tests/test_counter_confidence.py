"""F2 — lane-weighted, sample-size-aware counter scoring.

Two corrections over the old flat team-average counter score:
  * the direct lane opponent carries most of the weight (laning dominates);
  * a thin matchup sample is shrunk toward neutral so a fluke can't swing it.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sylqon.analysis.scoring import ChampionScorer
from sylqon.db import queries
from sylqon.db.schema import Base, Champion, ChampionCounter


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)()


def _champ(session, name, key):
    c = Champion(name=name, riot_key=key, slug=name.replace(" ", ""),
                 roles=["middle"], op_gg_stats={})
    session.add(c)
    session.flush()
    return c


def _counter(session, me, other, role, adv, games=None):
    session.add(ChampionCounter(champion_id=me.id, counter_id=other.id, role=role,
                                advantage_score=adv, games=games))


# -- lane weighting ----------------------------------------------------------
def test_lane_opponent_dominates_counter_score():
    session = _session()
    me = _champ(session, "Me", 1)
    lane = _champ(session, "Lane", 2)
    e2 = _champ(session, "E2", 3)
    e3 = _champ(session, "E3", 4)
    # Strong edge vs the lane opponent, neutral vs the rest of the team.
    _counter(session, me, lane, "middle", 8.0)
    _counter(session, me, e2, "middle", 0.0)
    _counter(session, me, e3, "middle", 0.0)
    session.commit()
    scorer = ChampionScorer()
    enemies = [lane.id, e2.id, e3.id]

    flat = scorer._counter_score(session, me.id, "middle", enemies)
    lane_weighted = scorer._counter_score(session, me.id, "middle", enemies,
                                          lane_enemy_id=lane.id)
    # Knowing the lane opponent lifts the read of a champion that specifically
    # beats them, instead of diluting it across the whole enemy team.
    assert lane_weighted > flat


def test_lane_weight_falls_back_to_flat_without_a_matchup():
    session = _session()
    me = _champ(session, "Me", 1)
    lane = _champ(session, "Lane", 2)
    e2 = _champ(session, "E2", 3)
    _counter(session, me, e2, "middle", 6.0)  # no row for the lane opponent
    session.commit()
    scorer = ChampionScorer()
    enemies = [lane.id, e2.id]
    flat = scorer._counter_score(session, me.id, "middle", enemies)
    # lane_enemy_id given but no matchup data for it → identical to flat average.
    assert scorer._counter_score(session, me.id, "middle", enemies,
                                 lane_enemy_id=lane.id) == flat


# -- sample-size shrinkage ---------------------------------------------------
def test_thin_sample_is_shrunk_toward_neutral():
    session = _session()
    me = _champ(session, "Me", 1)
    enemy = _champ(session, "Enemy", 2)
    _counter(session, me, enemy, "middle", 8.0, games=10)     # tiny sample
    session.commit()
    scorer = ChampionScorer()
    thin = scorer._counter_score(session, me.id, "middle", [enemy.id])

    # Same advantage, huge sample → trusted nearly fully.
    session2 = _session()
    me2 = _champ(session2, "Me", 1)
    en2 = _champ(session2, "Enemy", 2)
    _counter(session2, me2, en2, "middle", 8.0, games=5000)
    session2.commit()
    thick = scorer._counter_score(session2, me2.id, "middle", [en2.id])

    assert abs(thin - 50) < abs(thick - 50)   # thin sample closer to neutral
    assert thick > 80                          # strong, well-sampled edge stands


def test_missing_games_preserves_legacy_behaviour():
    session = _session()
    me = _champ(session, "Me", 1)
    enemy = _champ(session, "Enemy", 2)
    _counter(session, me, enemy, "middle", 8.0, games=None)  # legacy row
    session.commit()
    scorer = ChampionScorer()
    # No shrinkage applied: (8 + 10) / 20 * 100 = 90.
    assert scorer._counter_score(session, me.id, "middle", [enemy.id]) == 90.0


def test_counter_games_map_reads_sample_sizes():
    session = _session()
    me = _champ(session, "Me", 1)
    a = _champ(session, "A", 2)
    b = _champ(session, "B", 3)
    _counter(session, me, a, "middle", 3.0, games=250)
    _counter(session, me, b, "middle", 3.0, games=None)
    session.commit()
    got = queries.counter_games_map(session, me.id, "middle", [a.id, b.id])
    assert got == {a.id: 250}   # b absent (no sample stored)
