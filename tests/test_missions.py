"""Offline tests for the role-aware mission engine (overlay coach, Phase 2).

Drives synthetic ``LiveGameState`` snapshots through the pure evaluators and the
``MissionEngine`` — no game / network needed.

Run: python -m pytest tests/test_missions.py -q
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon.livegame.engine import MissionEngine
from sylqon.livegame.missions import (
    FARM_CS_DELTA,
    GOLD_SPEND,
    LEVEL_LEAD,
    NO_DEATH,
    OBJECTIVE,
    WARDING,
    Mission,
    evaluate,
    make_runtime,
    scaled_mission,
)
from sylqon.livegame.state import LiveGameState


def live(**kw) -> LiveGameState:
    return LiveGameState(active=True, **kw)


# -- evaluators --------------------------------------------------------------
def test_no_death_completes_and_fails():
    m = Mission("t", "top", NO_DEATH, {"duration": 120}, 20, "x")
    rt = make_runtime(m, live(game_time=0, deaths=0))
    assert evaluate(rt, live(game_time=60, deaths=0))[0] == "active"
    assert evaluate(rt, live(game_time=120, deaths=0))[0] == "completed"
    assert evaluate(rt, live(game_time=60, deaths=1))[0] == "failed"


def test_farm_delta_complete_and_deadline_fail():
    m = Mission("f", "bottom", FARM_CS_DELTA, {"cs_delta": 40, "duration": 180}, 30, "x")
    rt = make_runtime(m, live(game_time=10, cs=100))     # baseline cs=100, deadline=190
    assert evaluate(rt, live(game_time=60, cs=130))[0] == "active"      # +30 < 40
    assert evaluate(rt, live(game_time=60, cs=140))[0] == "completed"   # +40
    assert evaluate(rt, live(game_time=200, cs=120))[0] == "failed"     # past deadline, +20


def test_objective_and_warding():
    o = Mission("o", "jungle", OBJECTIVE,
                {"objectives": ["dragons", "heralds"], "count": 1, "duration": 240}, 30, "x")
    base = live(game_time=0, objectives={"dragons": {"ally": 0, "enemy": 0}})
    rt = make_runtime(o, base)
    after = live(game_time=100, objectives={"dragons": {"ally": 1, "enemy": 0}})
    assert evaluate(rt, after)[0] == "completed"

    w = Mission("w", "utility", WARDING, {"ward_count": 3, "duration": 180}, 25, "x")
    rtw = make_runtime(w, live(game_time=0, ward_score=2.0))
    assert evaluate(rtw, live(game_time=60, ward_score=4.0))[0] == "active"      # +2
    assert evaluate(rtw, live(game_time=60, ward_score=5.0))[0] == "completed"   # +3


# -- engine ------------------------------------------------------------------
def test_engine_assigns_two_role_missions():
    eng = MissionEngine("bottom", rng=random.Random(0))
    out = eng.tick(live(game_time=10, cs=50, deaths=0))
    assert out["active"] is True
    assert len(out["missions"]) == 2
    assert all(rt.mission.role == "bottom" for rt in eng.active)   # never role-incompatible


def test_engine_refills_and_fires_callback():
    resolved = []
    eng = MissionEngine("top", rng=random.Random(2),
                        on_resolve=lambda m, r: resolved.append((m.id, r)))
    eng.tick(live(game_time=0, deaths=0, cs=0))
    assert len(eng.active) == 2
    # Every top mission is death-sensitive → a death fails the active ones, which
    # are then refilled back up to the cap.
    eng.tick(live(game_time=30, deaths=1, cs=0))
    assert len(eng.active) == 2
    assert any(result == "failed" for _, result in resolved)


def test_session_reset_on_clock_drop():
    eng = MissionEngine("middle", rng=random.Random(3))
    eng.tick(live(game_time=600, cs=200))
    s1 = eng.session_id
    eng.tick(live(game_time=605, cs=210))
    assert eng.session_id == s1                  # same game
    eng.tick(live(game_time=5, cs=0))            # new game clock restarted
    assert eng.session_id != s1


def test_no_game_clears_missions():
    eng = MissionEngine("top", rng=random.Random(4))
    eng.tick(live(game_time=10))
    assert eng.active
    out = eng.tick(LiveGameState.none())
    assert out["active"] is False and out["missions"] == []
    assert eng.active == []


def test_role_switch_clears():
    eng = MissionEngine("top", rng=random.Random(5))
    eng.tick(live(game_time=10))
    eng.set_role("jungle")
    assert eng.active == [] and eng.role == "jungle"


# -- Phase 5: decision missions + rank-adaptive difficulty -------------------
def test_gold_spend_completes_on_a_back():
    m = Mission("g", "bottom", GOLD_SPEND, {"gold_spent": 1000, "duration": 180}, 25, "x")
    rt = make_runtime(m, live(game_time=100, current_gold=1400.0))
    # Gold climbs but nothing spent → still active.
    assert evaluate(rt, live(game_time=140, current_gold=1600.0))[0] == "active"
    # Backed and bought (gold dropped past the target) → completed.
    assert evaluate(rt, live(game_time=160, current_gold=300.0))[0] == "completed"
    # Never spent by the deadline → failed.
    assert evaluate(rt, live(game_time=300, current_gold=1900.0))[0] == "failed"


def test_level_lead_scored_at_deadline():
    m = Mission("l", "middle", LEVEL_LEAD, {"lead": 0, "duration": 180}, 25, "x")
    rt = make_runtime(m, live(game_time=100, level_diff=0))
    assert evaluate(rt, live(game_time=200, level_diff=1))[0] == "active"     # window open
    # At the deadline: even-or-ahead completes, behind fails.
    assert evaluate(rt, live(game_time=280, level_diff=0))[0] == "completed"
    assert evaluate(rt, live(game_time=280, level_diff=-1))[0] == "failed"


def test_scaled_mission_raises_and_lowers_goals_within_range():
    m = Mission("f", "bottom", FARM_CS_DELTA, {"cs_delta": 40, "duration": 180}, 30, "x")
    assert scaled_mission(m, 1.0) is m                       # baseline is a no-op
    assert scaled_mission(m, 1.25).params["cs_delta"] == 50  # harder for high elo
    assert scaled_mission(m, 0.8).params["cs_delta"] == 32   # gentler for low elo
    assert scaled_mission(m, 1.25).params["duration"] == 180  # window is untouched
    assert scaled_mission(m, 1.25).id == m.id                # identity preserved


def test_set_tier_scales_engine_difficulty():
    eng = MissionEngine("bottom", rng=random.Random(7))
    eng.set_tier("IRON")
    assert eng.difficulty < 1.0
    eng.set_tier("DIAMOND")
    assert eng.difficulty > 1.0
    eng.set_tier("")                       # unknown/unranked → baseline
    assert eng.difficulty == 1.0


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
