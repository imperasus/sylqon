"""Offline tests for the state-reactive coaching triggers (overlay coach, Phase 3).

No game / network — drives synthetic ``LiveGameState`` snapshots through the
``TriggerEngine`` and asserts the edge-triggered, rate-limited alerts.

Run: python -m pytest tests/test_live_triggers.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon.livegame.state import LiveGameState
from sylqon.livegame.triggers import (
    DEATH_REVIEW,
    ENEMY_DOWN,
    ITEM_SPIKE,
    LOW_HP,
    MATCHUP_PLAN,
    OBJECTIVE_SETUP,
    RECALL_GOLD,
    ULT_SPIKE,
    TriggerEngine,
)


def _state(game_time=300.0, *, role="bottom", my_name="Me", ult=0, gold=0.0,
           hp_pct=100.0, is_dead=False, my_items=0, deaths=0, last_death=None,
           matchup=None, enemy_dead=False, enemy_respawn=0.0, dragon=None, baron=None):
    roster = [
        {"side": "ally", "role": role, "name": my_name, "completed_items": my_items},
        {"side": "enemy", "role": role, "name": "Enemy", "completed_items": 0,
         "is_dead": enemy_dead, "respawn_timer": enemy_respawn},
    ]
    timers = {}
    if dragon is not None:
        timers["dragon"] = dragon
    if baron is not None:
        timers["baron"] = baron
    return LiveGameState(
        active=True, game_time=game_time, my_name=my_name, role=role,
        is_dead=is_dead, current_gold=gold, deaths=deaths,
        champion_stats={"health_pct": hp_pct},
        abilities={"q": 0, "w": 0, "e": 0, "r": ult, "ult_level": ult},
        roster=roster, objective_timers=timers,
        last_death=last_death or {}, matchup=matchup or {},
    )


def _cats(alerts):
    return {a["category"] for a in alerts}


def test_first_tick_only_primes_no_burst():
    eng = TriggerEngine()
    assert eng.evaluate(_state(ult=1, hp_pct=10.0)) == []  # baseline only


def test_no_game_returns_empty_and_resets():
    eng = TriggerEngine()
    eng.evaluate(_state())                       # prime
    assert eng.evaluate(LiveGameState.none()) == []


def test_ult_spike_fires_on_unlock():
    eng = TriggerEngine()
    eng.evaluate(_state(ult=0))
    alerts = eng.evaluate(_state(game_time=360.0, ult=1))
    assert ULT_SPIKE in _cats(alerts)
    a = next(a for a in alerts if a["category"] == ULT_SPIKE)
    assert "level 6" in a["text"] and a["rationale"]     # carries the "why"


def test_item_spike_fires_when_my_completed_count_rises():
    eng = TriggerEngine()
    eng.evaluate(_state(my_items=1))
    alerts = eng.evaluate(_state(game_time=360.0, my_items=2))
    assert ITEM_SPIKE in _cats(alerts)


def test_enemy_down_fires_on_death_transition():
    eng = TriggerEngine()
    eng.evaluate(_state(enemy_dead=False))
    alerts = eng.evaluate(_state(game_time=360.0, enemy_dead=True, enemy_respawn=18.0))
    assert ENEMY_DOWN in _cats(alerts)


def test_enemy_down_ignored_when_respawn_too_short():
    eng = TriggerEngine()
    eng.evaluate(_state(enemy_dead=False))
    alerts = eng.evaluate(_state(game_time=360.0, enemy_dead=True, enemy_respawn=5.0))
    assert ENEMY_DOWN not in _cats(alerts)


def test_recall_gold_fires_crossing_up_then_rearms_after_back():
    eng = TriggerEngine()
    eng.evaluate(_state(gold=1000.0))
    a1 = eng.evaluate(_state(game_time=360.0, gold=1400.0))
    assert RECALL_GOLD in _cats(a1)
    # Stays high but already fired → suppressed (armed flag consumed).
    a2 = eng.evaluate(_state(game_time=420.0, gold=1500.0))
    assert RECALL_GOLD not in _cats(a2)
    # Spends gold (a back), then banks again → re-armed, fires once more.
    eng.evaluate(_state(game_time=480.0, gold=200.0))
    a3 = eng.evaluate(_state(game_time=600.0, gold=1400.0))
    assert RECALL_GOLD in _cats(a3)


def test_objective_setup_fires_entering_dragon_window():
    eng = TriggerEngine()
    eng.evaluate(_state(dragon=60.0))
    alerts = eng.evaluate(_state(game_time=360.0, dragon=40.0))
    assert OBJECTIVE_SETUP in _cats(alerts)


def test_baron_setup_only_after_first_spawn():
    eng = TriggerEngine()
    # Before 20:00 the baron window must not fire.
    eng.evaluate(_state(game_time=600.0, baron=70.0))
    early = eng.evaluate(_state(game_time=660.0, baron=40.0))
    assert OBJECTIVE_SETUP not in _cats(early)


def test_low_hp_fires_and_outranks_opportunity():
    eng = TriggerEngine()
    eng.evaluate(_state(hp_pct=60.0, ult=0))
    # HP crashes AND ult comes up on the same tick → both detected, low-hp first.
    alerts = eng.evaluate(_state(game_time=360.0, hp_pct=18.0, ult=1))
    assert alerts[0]["category"] == LOW_HP        # safety outranks the spike
    assert LOW_HP in _cats(alerts) and ULT_SPIKE in _cats(alerts)


def test_at_most_two_alerts_per_tick():
    eng = TriggerEngine()
    eng.evaluate(_state(hp_pct=60.0, ult=0, my_items=0, enemy_dead=False))
    alerts = eng.evaluate(_state(game_time=360.0, hp_pct=18.0, ult=1, my_items=1,
                                 enemy_dead=True, enemy_respawn=20.0))
    assert len(alerts) <= 2
    # The two highest-priority survive: low-hp (100) and enemy-down (70).
    assert _cats(alerts) == {LOW_HP, ENEMY_DOWN}


def test_cooldown_suppresses_repeat_within_window():
    eng = TriggerEngine()
    eng.evaluate(_state(enemy_dead=False))
    a1 = eng.evaluate(_state(game_time=360.0, enemy_dead=True, enemy_respawn=20.0))
    assert ENEMY_DOWN in _cats(a1)
    # Enemy respawns, dies again 10s later — inside the 35s cooldown → suppressed.
    eng.evaluate(_state(game_time=365.0, enemy_dead=False))
    a2 = eng.evaluate(_state(game_time=370.0, enemy_dead=True, enemy_respawn=20.0))
    assert ENEMY_DOWN not in _cats(a2)


def test_death_review_solo_kill():
    eng = TriggerEngine()
    eng.evaluate(_state(deaths=0))
    alerts = eng.evaluate(_state(game_time=360.0, deaths=1,
                                 last_death={"killer_champ": "Zed", "assisters": 0}))
    assert DEATH_REVIEW in _cats(alerts)
    a = next(a for a in alerts if a["category"] == DEATH_REVIEW)
    assert "Zed" in a["text"] and a["rationale"]


def test_death_review_collapse_when_assisted():
    eng = TriggerEngine()
    eng.evaluate(_state(deaths=0))
    alerts = eng.evaluate(_state(game_time=360.0, deaths=1,
                                 last_death={"killer_champ": "Lee Sin", "assisters": 2}))
    a = next(a for a in alerts if a["category"] == DEATH_REVIEW)
    assert "3-man collapse" in a["text"]     # killer + 2 assisters


def test_death_review_only_on_new_death():
    eng = TriggerEngine()
    eng.evaluate(_state(deaths=1, last_death={"killer_champ": "Zed", "assisters": 0}))
    # deaths unchanged → no re-review of the same death.
    alerts = eng.evaluate(_state(game_time=360.0, deaths=1,
                                 last_death={"killer_champ": "Zed", "assisters": 0}))
    assert DEATH_REVIEW not in _cats(alerts)


def test_matchup_plan_fires_once_early():
    eng = TriggerEngine()
    eng.evaluate(_state(game_time=20.0))
    a1 = eng.evaluate(_state(game_time=40.0,
                             matchup={"opponent": "Zed", "playstyle": "Respect the all-in.",
                                      "tempo": "Ignite means early all-in."}))
    assert MATCHUP_PLAN in _cats(a1)
    assert "Zed" in next(a for a in a1 if a["category"] == MATCHUP_PLAN)["text"]
    # Once per game only — does not repeat on later ticks.
    a2 = eng.evaluate(_state(game_time=80.0,
                             matchup={"opponent": "Zed", "playstyle": "Respect the all-in.",
                                      "tempo": ""}))
    assert MATCHUP_PLAN not in _cats(a2)


def test_matchup_plan_not_pitched_late():
    eng = TriggerEngine()
    eng.evaluate(_state(game_time=600.0))
    alerts = eng.evaluate(_state(game_time=660.0,
                                 matchup={"opponent": "Zed", "playstyle": "x", "tempo": ""}))
    assert MATCHUP_PLAN not in _cats(alerts)   # past the opening-minutes window


def test_new_game_resets_state():
    eng = TriggerEngine()
    eng.evaluate(_state(game_time=800.0, ult=0))
    # Clock jumps back to ~0 => new game; next tick primes again (no burst).
    assert eng.evaluate(_state(game_time=30.0, ult=1)) == []


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
