"""F4b — pick-order counterability advisory.

The recommended pick is only "safe to lock" if the enemy can no longer adapt to
it. This surfaces how exposed the pick is given the enemy picks still to come.
"""
from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sylqon.db.schema import Base, Champion, ChampionCounter
from sylqon.runtime import PipelineRunner


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)()


def _champ(session, name, key):
    c = Champion(name=name, riot_key=key, slug=name, roles=["middle"], op_gg_stats={})
    session.add(c)
    session.flush()
    return c


def _ctx(remaining, enemies=(), allies=()):
    return SimpleNamespace(
        my_role="middle", my_champion="", enemy_picks_after_me=remaining,
        enemies=[SimpleNamespace(name=n) for n in enemies],
        allies=[SimpleNamespace(name=n) for n in allies], bans=[])


def _seed_counters(session, pick, counter_names):
    """Make each named champion a strong counter to ``pick`` in middle."""
    for i, n in enumerate(counter_names):
        c = _champ(session, n, 900 + i)
        session.add(ChampionCounter(champion_id=c.id, counter_id=pick.id,
                                    role="middle", advantage_score=7.0))


def test_safe_when_no_enemy_picks_remain(monkeypatch):
    r = PipelineRunner()
    risk = r._counter_pick_risk(_ctx(remaining=0), "Ahri")
    assert risk["level"] == "safe"


def test_high_risk_with_many_open_counters(monkeypatch):
    session = _session()
    pick = _champ(session, "Ahri", 103)
    _seed_counters(session, pick, ["Kassadin", "Fizz", "LeBlanc"])
    session.commit()
    monkeypatch.setattr("sylqon.db.session.get_session", lambda: session)

    r = PipelineRunner()
    risk = r._counter_pick_risk(_ctx(remaining=2), "Ahri")
    assert risk["level"] == "high"
    assert risk["available"] == 3


def test_taken_counters_do_not_count(monkeypatch):
    session = _session()
    pick = _champ(session, "Ahri", 103)
    _seed_counters(session, pick, ["Kassadin", "Fizz", "LeBlanc"])
    session.commit()
    monkeypatch.setattr("sylqon.db.session.get_session", lambda: session)

    r = PipelineRunner()
    # Two of the three counters are already picked/banned → only one remains.
    ctx = _ctx(remaining=2, enemies=["Kassadin"], allies=["Fizz"])
    risk = r._counter_pick_risk(ctx, "Ahri")
    assert risk["available"] == 1
    assert risk["level"] == "moderate"


def test_none_when_pick_unknown_to_db(monkeypatch):
    session = _session()
    session.commit()
    monkeypatch.setattr("sylqon.db.session.get_session", lambda: session)
    r = PipelineRunner()
    assert r._counter_pick_risk(_ctx(remaining=1), "Nonexistent") is None
