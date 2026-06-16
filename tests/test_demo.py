"""Offline tests for overlay demo mode (Phase 5).

Run: python -m pytest tests/test_demo.py -q
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon.livegame.demo import fake_live_state
from sylqon.livegame.engine import MissionEngine


def test_fake_state_progresses_without_deaths():
    s0 = fake_live_state(0, "bottom")
    s1 = fake_live_state(60, "bottom")
    assert s0.active and s1.active
    assert s1.game_time > s0.game_time
    assert s1.cs > s0.cs
    assert s0.deaths == 0 and s1.deaths == 0
    assert s1.role == "bottom"


def test_fake_objective_after_threshold():
    early = fake_live_state(5, "jungle")     # game_time 30 < 90
    later = fake_live_state(30, "jungle")    # game_time 180 >= 90
    assert early.objectives["dragons"]["ally"] == 0
    assert later.objectives["dragons"]["ally"] == 1


def test_engine_completes_missions_via_demo():
    resolved = []
    eng = MissionEngine("bottom", rng=random.Random(0),
                        on_resolve=lambda m, r: resolved.append(r))
    for elapsed in range(0, 80):
        eng.tick(fake_live_state(elapsed, "bottom"))
    assert any(r == "completed" for r in resolved)   # missions resolve over the run


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
