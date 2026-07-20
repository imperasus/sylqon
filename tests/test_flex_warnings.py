"""F4c — flex-aware lane warnings.

A revealed enemy that plays several lanes carries an inferred lane plus a
confidence; when the inference is a genuine toss-up it is flagged ``tentative``
so the read widens instead of committing to one lane opponent.
"""
from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sylqon.db.schema import Base, Champion
from sylqon.runtime import PipelineRunner


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)()


def _champ(session, name, key, pick_rates: dict):
    session.add(Champion(name=name, riot_key=key, slug=name, roles=list(pick_rates),
                         op_gg_stats={r: {"pick_rate": pr} for r, pr in pick_rates.items()}))
    session.flush()


def _enemy(name, key, role=""):
    return SimpleNamespace(name=name, champion_id=key, role=role)


def _ctx(enemies):
    return SimpleNamespace(enemies=enemies)


def test_even_flex_is_flagged_tentative(monkeypatch):
    session = _session()
    _champ(session, "Sett", 875, {"top": 6.0, "utility": 5.0})  # near 50/50
    session.commit()
    monkeypatch.setattr("sylqon.db.session.get_session", lambda: session)

    r = PipelineRunner()
    out = r._flex_warnings(_ctx([_enemy("Sett", 875)]))
    assert len(out) == 1
    assert out[0]["tentative"] is True
    assert set(out[0]["roles"]) == {"top", "utility"}


def test_concentrated_flex_is_confident(monkeypatch):
    session = _session()
    _champ(session, "Ahri", 103, {"middle": 10.0, "top": 1.0})  # clearly mid
    session.commit()
    monkeypatch.setattr("sylqon.db.session.get_session", lambda: session)

    r = PipelineRunner()
    out = r._flex_warnings(_ctx([_enemy("Ahri", 103)]))
    assert len(out) == 1
    assert out[0]["tentative"] is False
    assert out[0]["confidence"] >= 0.55


def test_single_role_champion_not_flagged(monkeypatch):
    session = _session()
    _champ(session, "Darius", 122, {"top": 12.0})  # one lane only
    session.commit()
    monkeypatch.setattr("sylqon.db.session.get_session", lambda: session)

    r = PipelineRunner()
    assert r._flex_warnings(_ctx([_enemy("Darius", 122)])) == []
