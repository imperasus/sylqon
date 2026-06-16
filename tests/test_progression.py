"""Offline tests for the overlay progression service (Phase 3).

In-memory SQLite; drives ProgressionService with synthetic Mission resolutions.

Run: python -m pytest tests/test_progression.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sylqon.db.schema import Base, MissionRun
from sylqon.livegame.missions import FARM_CS_DELTA, NO_DEATH, Mission
from sylqon.livegame.progression import ProgressionService


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)()


def _mission(mtype=NO_DEATH, points=20, role="top"):
    return Mission(f"m_{mtype}", role, mtype, {"duration": 120}, points, "x")


def test_profile_autocreate_and_label():
    s = _session()
    svc = ProgressionService()
    p = svc.ensure_profile(s, "Faker")
    assert p.id == 1 and p.summoner_name == "Faker"
    assert p.total_points == 0 and p.level == 1
    # second call relabels, doesn't duplicate
    p2 = svc.ensure_profile(s, "Hide on bush")
    assert p2.id == 1 and p2.summoner_name == "Hide on bush"


def test_award_points_and_level():
    s = _session()
    svc = ProgressionService()
    p = svc.ensure_profile(s, "me")
    for _ in range(6):  # 6 * 20 = 120 points -> level 2
        svc.record_resolution(s, p, _mission(points=20), "completed", game_session="g1")
    assert p.total_points == 120
    assert p.level == 2                      # 120 // 100 + 1
    # a failed mission persists but awards nothing
    svc.record_resolution(s, p, _mission(points=20), "failed", game_session="g1")
    assert p.total_points == 120
    assert s.query(MissionRun).count() == 7


def test_badges_first_and_deathless():
    s = _session()
    svc = ProgressionService()
    p = svc.ensure_profile(s, "me")
    svc.record_resolution(s, p, _mission(FARM_CS_DELTA, points=10), "completed")
    assert "first_mission" in (p.unlocked_badges or [])
    assert "deathless_10" not in (p.unlocked_badges or [])
    for _ in range(10):  # 10 no-death completions
        svc.record_resolution(s, p, _mission(NO_DEATH, points=10), "completed")
    badges = p.unlocked_badges or []
    assert "deathless_10" in badges
    # level_5 unlocks via points: total so far = 10 + 100 = 110 -> level 2 (no badge)
    serialized = svc.serialize_profile(p)
    assert any(b["id"] == "deathless_10" for b in serialized["badges"])


def test_reset():
    s = _session()
    svc = ProgressionService()
    p = svc.ensure_profile(s, "me")
    svc.record_resolution(s, p, _mission(points=50), "completed")
    assert p.total_points == 50
    svc.reset(s)
    p2 = svc.get_profile(s)
    assert p2.total_points == 0 and p2.level == 1 and (p2.unlocked_badges or []) == []
    assert s.query(MissionRun).count() == 0


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
