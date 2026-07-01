"""Offline tests for the per-champion mission redesign (overlay coach v2).

Covers: AI-mission validation/clamping, the queue-first engine source + general
fallback, per-champion + account progression, and the post-game top-up with a
fake (offline) Ollama engine.

Run: python -m pytest tests/test_champion_missions.py -q
"""
from __future__ import annotations

import random
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sylqon.db.schema import (
    Base,
    Champion,
    ChampionMission,
    MatchHistory,
)
from sylqon.livegame import champion_missions
from sylqon.livegame.engine import MissionEngine
from sylqon.livegame.missions import (
    FARM_CS_DELTA,
    NO_DEATH,
    OBJECTIVE,
    mission_from_row,
    normalize_mission,
)
from sylqon.livegame.progression import ProgressionService
from sylqon.livegame.state import LiveGameState


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)()


def live(**kw) -> LiveGameState:
    return LiveGameState(active=True, **kw)


# -- validation --------------------------------------------------------------
def test_normalize_clamps_and_accepts():
    out = normalize_mission({"type": FARM_CS_DELTA,
                             "params": {"cs_delta": 999, "duration": 9999, "no_death": True},
                             "reward_points": 500, "text": "Farm hard on Jinx"})
    assert out["type"] == FARM_CS_DELTA
    assert out["params"]["cs_delta"] == 90        # clamped to max
    assert out["params"]["duration"] == 360       # clamped to max
    assert out["params"]["no_death"] is True
    assert out["reward_points"] == 50             # clamped to reward max
    assert out["text"] == "Farm hard on Jinx"


def test_normalize_rejects_unknown_type_and_missing_required():
    assert normalize_mission({"type": "make_coffee", "params": {}}) is None
    # CS/min requires both cs_per_min and duration
    assert normalize_mission({"type": "cs_per_min_threshold",
                              "params": {"cs_per_min": 7}}) is None


def test_normalize_enum_list_filtered():
    out = normalize_mission({"type": OBJECTIVE,
                             "params": {"count": 2, "objectives": ["dragons", "moon"]}})
    assert out["params"]["objectives"] == ["dragons"]   # junk dropped
    assert out["params"]["count"] == 2


def test_normalize_synthesizes_text_when_missing():
    out = normalize_mission({"type": NO_DEATH, "params": {"duration": 120}})
    assert "120s" in out["text"]


# -- engine queue-first + fallback -------------------------------------------
def _seed_queue(session, champion_id, n=2):
    for i in range(n):
        session.add(ChampionMission(
            champion_id=champion_id, mission_type=NO_DEATH,
            params={"duration": 120}, reward_points=20, text=f"AI mission {i}",
            source="ai", status="pending"))
    session.flush()


def test_engine_serves_queue_before_catalog():
    s = _session()
    champ = Champion(name="Ahri", riot_key=103, roles=["middle"])
    s.add(champ); s.flush()
    _seed_queue(s, champ.id, n=2)

    def source(role, champion):
        return champion_missions.load_pending(s, champ.id, role)

    eng = MissionEngine("middle", mission_source=source, rng=random.Random(0))
    eng.set_context("middle", "Ahri")
    out = eng.tick(live(game_time=10, cs=0, deaths=0))
    # both active missions come from the AI queue (ids tagged cm:)
    assert len(out["missions"]) == 2
    assert all(m["id"].startswith("cm:") for m in out["missions"])


def test_engine_falls_back_to_catalog_when_queue_empty():
    eng = MissionEngine("top", mission_source=lambda r, c: [], rng=random.Random(1))
    eng.set_context("top", "Garen")
    out = eng.tick(live(game_time=10, cs=0, deaths=0))
    assert len(out["missions"]) == 2
    assert all(not m["id"].startswith("cm:") for m in out["missions"])  # role catalog


def test_resolved_queue_mission_not_reserved_same_game():
    s = _session()
    champ = Champion(name="Ahri", riot_key=103, roles=["middle"])
    s.add(champ); s.flush()
    _seed_queue(s, champ.id, n=3)
    eng = MissionEngine("middle", max_active=1,
                        mission_source=lambda r, c: champion_missions.load_pending(s, champ.id, r),
                        rng=random.Random(0))
    eng.set_context("middle", "Ahri")
    eng.tick(live(game_time=0, deaths=0))
    first = eng.active[0].mission.id
    eng.tick(live(game_time=200, deaths=0))   # no_death completes at 120s -> resolves
    assert first in eng._resolved_ids
    assert all(rt.mission.id != first for rt in eng.active)  # not re-served


# -- per-champion progression ------------------------------------------------
def _mission(mtype=NO_DEATH, points=20, role="middle", mid="m1"):
    from sylqon.livegame.missions import Mission
    return Mission(mid, role, mtype, {"duration": 120}, points, "x")


def test_points_accrue_to_champion_and_account():
    s = _session()
    champ = Champion(name="Ahri", riot_key=103, roles=["middle"])
    s.add(champ); s.flush()
    svc = ProgressionService()
    p = svc.ensure_profile(s, "me")
    svc.record_resolution(s, p, _mission(points=30), "completed", champion_id=champ.id)
    svc.record_resolution(s, p, _mission(points=30), "completed", champion_id=champ.id)
    cp = svc.champion_progress(s, champ.id)
    assert cp.total_points == 60
    assert p.total_points == 60            # account == sum of champion points
    # failed mission awards nothing to either tier
    svc.record_resolution(s, p, _mission(points=30), "failed", champion_id=champ.id)
    assert svc.champion_progress(s, champ.id).total_points == 60


def test_queue_row_flipped_completed_on_resolution():
    s = _session()
    champ = Champion(name="Ahri", riot_key=103, roles=["middle"])
    s.add(champ); s.flush()
    _seed_queue(s, champ.id, n=1)
    row = s.query(ChampionMission).first()
    svc = ProgressionService()
    p = svc.ensure_profile(s, "me")
    m = mission_from_row(row, "middle")
    svc.record_resolution(s, p, m, "completed", champion_id=champ.id)
    assert s.get(ChampionMission, row.id).status == "completed"


def test_champion_level_derivation():
    s = _session()
    champ = Champion(name="Ahri", riot_key=103, roles=["middle"])
    s.add(champ); s.flush()
    svc = ProgressionService()
    p = svc.ensure_profile(s, "me")
    for _ in range(4):  # 4 * 30 = 120 -> level 2
        svc.record_resolution(s, p, _mission(points=30), "completed", champion_id=champ.id)
    cp = svc.champion_progress(s, champ.id)
    assert cp.level == 2
    ser = svc.serialize_champion_progress(cp, "Ahri")
    assert ser["level"] == 2 and ser["points_into_level"] == 20


# -- post-game top-up with a fake engine -------------------------------------
class _FakeEngine:
    """Offline stand-in for OllamaEngine: returns a scripted missions payload."""
    def __init__(self, payload):
        self._payload = payload

    def available(self):
        return True

    def evaluate(self, prompt, options=None):
        return self._payload


def test_topup_inserts_validated_missions():
    s = _session()
    champ = Champion(name="Jinx", riot_key=222, roles=["bottom"])
    s.add(champ); s.flush()
    s.add(MatchHistory(game_id="g1", champion_id=champ.id, role="bottom",
                       result="Loss", kda_json={"kills": 2, "deaths": 7, "assists": 3},
                       stats_json={"cs_per_min": 5.1, "vision_score": 8},
                       played_at=datetime.utcnow()))
    s.flush()
    engine = _FakeEngine({"missions": [
        {"type": NO_DEATH, "params": {"duration": 150}, "reward_points": 30, "text": "Survive on Jinx"},
        {"type": FARM_CS_DELTA, "params": {"cs_delta": 40, "duration": 180}, "reward_points": 30, "text": "Farm up"},
        {"type": "bogus", "params": {}},                       # rejected
    ]})
    inserted = champion_missions.topup(s, champ.id, "Jinx", "bottom", engine, target=3)
    assert inserted == 2                                       # bogus dropped
    pending = champion_missions.load_pending(s, champ.id, "bottom")
    assert len(pending) == 2
    assert all(p.id.startswith("cm:") for p in pending)


def test_topup_noop_when_queue_full():
    s = _session()
    champ = Champion(name="Jinx", riot_key=222, roles=["bottom"])
    s.add(champ); s.flush()
    _seed_queue(s, champ.id, n=3)
    engine = _FakeEngine({"missions": [{"type": NO_DEATH, "params": {"duration": 120}}]})
    assert champion_missions.topup(s, champ.id, "Jinx", "bottom", engine, target=3) == 0


def test_topup_skips_when_engine_unavailable():
    s = _session()
    champ = Champion(name="Jinx", riot_key=222, roles=["bottom"])
    s.add(champ); s.flush()

    class _Down(_FakeEngine):
        def available(self):
            return False

    assert champion_missions.topup(s, champ.id, "Jinx", "bottom", _Down({}), target=3) == 0
    assert champion_missions.count_pending(s, champ.id) == 0


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
