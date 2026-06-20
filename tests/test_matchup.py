"""Offline tests for the post-lock matchup scorecard + AI lane plan.

In-memory SQLite seeded with champions, counters, synergies and builds; a fake
catalog for slug resolution and a fake Ollama engine for the lane plan. No
network.

Run: python -m pytest tests/test_matchup.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sylqon.ai.lane_plan import LaneCoach
from sylqon.analysis.matchup import compute_matchup
from sylqon.db.schema import (
    Base,
    Champion,
    ChampionBuild,
    ChampionCounter,
    ChampionSynergy,
)
from sylqon.lcu.lobby import ChampPick, MatchContext


class FakeCatalog:
    """Minimal Catalog stand-in: champion_id (riot key) -> {'id': slug}."""

    def __init__(self, slugs: dict[int, str]) -> None:
        self._slugs = slugs

    def champion_by_key(self, key):
        slug = self._slugs.get(key)
        return {"id": slug} if slug else None


class FakeEngine:
    def __init__(self, available=True, response=None) -> None:
        self._a, self._r = available, response

    def available(self):
        return self._a

    def evaluate(self, prompt, options=None):
        return self._r


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)()


def _champ(session, name, key, role, tier=3, win_rate=50.0):
    c = Champion(name=name, riot_key=key, slug=name, roles=[role],
                 op_gg_stats={role: {"tier": tier, "win_rate": win_rate}})
    session.add(c)
    session.flush()
    session.add(ChampionBuild(champion_id=c.id, role=role,
                              build_json={"items": []}, win_rate=win_rate))
    return c


def _pick(name, key, role, side, *, locked=True, damage="AP", threats=None, tags=None):
    return ChampPick(name=name, champion_id=key, role=role, side=side,
                     damage_type=damage, tags=tags or [], threats=threats or [],
                     locked=locked)


def _ctx(allies, enemies, *, champ="Malzahar", key=90, role="middle"):
    return MatchContext(
        summoner_id=1, my_champion=champ, my_champion_id=key, my_role=role,
        locked=True, all_locked=True, my_turn=False,
        enemies=enemies, allies=allies, fingerprint="t")


def _seed_world(session):
    me = _champ(session, "Malzahar", 90, "middle", tier=1, win_rate=52.0)
    leona = _champ(session, "Leona", 89, "utility")
    yasuo = _champ(session, "Yasuo", 157, "middle", tier=2)
    cait = _champ(session, "Caitlyn", 51, "bottom", tier=2)
    session.add(ChampionCounter(champion_id=me.id, counter_id=yasuo.id,
                                role="middle", advantage_score=3.5))
    session.add(ChampionCounter(champion_id=me.id, counter_id=cait.id,
                                role="middle", advantage_score=-1.5))
    session.add(ChampionSynergy(champion_id=me.id, synergy_id=leona.id,
                                role="middle", synergy_score=7.0))
    session.commit()
    return FakeCatalog({90: "Malzahar", 89: "Leona", 157: "Yasuo", 51: "Caitlyn"})


def test_matchup_scorecard_shape_and_values():
    session = _session()
    catalog = _seed_world(session)
    ctx = _ctx(
        allies=[_pick("Leona", 89, "utility", "ally", tags=["Tank"])],
        enemies=[_pick("Yasuo", 157, "middle", "enemy", damage="AD",
                       threats=["burst_ad"]),
                 _pick("Caitlyn", 51, "bottom", "enemy", damage="AD")],
    )

    m = compute_matchup(session, ctx, catalog)
    assert m["champion"] == {"name": "Malzahar", "slug": "Malzahar",
                             "role": "middle", "tier": 1}

    # counter component: avg(+3.5, -1.5)/2 = +1.0 -> ((1+10)/20)*100 = 55.0
    assert m["scores"]["counter"] == pytest.approx(55.0)
    assert m["win_rate_pct"] == 52.0

    # per-enemy counter values + lane-opponent flag (same role as me).
    yas = next(c for c in m["counters"] if c["name"] == "Yasuo")
    cait = next(c for c in m["counters"] if c["name"] == "Caitlyn")
    assert yas["value"] == 3.5 and yas["is_lane_opponent"] is True
    assert cait["value"] == -1.5 and cait["is_lane_opponent"] is False
    assert m["counter_avg"] == pytest.approx(1.0)  # (3.5 + -1.5) / 2

    # per-ally synergy value.
    assert m["synergies"][0] == {"name": "Leona", "slug": "Leona",
                                 "role": "utility", "value": 7.0}
    assert m["synergy_avg"] == 7.0

    # direct lane matchup carries the opponent's threat profile + advantage.
    lane = m["lane_opponent"]
    assert lane["name"] == "Yasuo" and lane["advantage"] == 3.5
    assert lane["damage_type"] == "AD" and "burst_ad" in lane["threats"]

    # lane score: counter 55.0 weighted 0.4 + lane 67.5 weighted 0.6 = 62.5
    assert m["lane_score"] == pytest.approx(62.5)


def test_matchup_handles_missing_pairs_and_no_lane_opponent():
    session = _session()
    catalog = _seed_world(session)
    # Only an off-role enemy revealed: no lane opponent, no counter row.
    ctx = _ctx(allies=[], enemies=[_pick("Caitlyn", 51, "bottom", "enemy")])

    m = compute_matchup(session, ctx, catalog)
    assert m["lane_opponent"] is None
    assert all(not c["is_lane_opponent"] for c in m["counters"])
    assert m["counters"][0]["value"] == -1.5     # Malzahar vs Caitlyn seeded
    assert m["synergies"] == [] and m["synergy_avg"] is None
    # No direct opponent -> lane score falls back to the counter component.
    assert m["lane_score"] == m["scores"]["counter"]


def test_matchup_none_when_champion_not_in_db():
    session = _session()
    catalog = _seed_world(session)
    ctx = _ctx(allies=[], enemies=[], champ="Aurelion Sol", key=136)
    assert compute_matchup(session, ctx, catalog) is None


def test_lane_plan_parses_and_degrades():
    ctx = _ctx(
        allies=[_pick("Leona", 89, "utility", "ally")],
        enemies=[_pick("Yasuo", 157, "middle", "enemy", damage="AD")],
    )
    matchup = {"lane_opponent": {"name": "Yasuo", "damage_type": "AD",
                                 "threats": ["burst_ad"], "advantage": 3.5}}
    intel = {"enemy_comp": {"label": "Pick / Assassinate",
                            "counter_plan": "Never walk alone."}}

    plan = LaneCoach(FakeEngine(response={
        "early": "x" * 300, "mid": "Group for picks.", "late": "Hold suppress.",
        "win_condition": "Delete their carry in a 5v5."})).plan(ctx, matchup, intel)
    assert len(plan["early"]) == 240          # clipped
    assert plan["mid"] == "Group for picks."
    assert plan["win_condition"] == "Delete their carry in a 5v5."

    # Empty payload -> None (no better than the deterministic scorecard).
    assert LaneCoach(FakeEngine(response={})).plan(ctx, matchup, intel) is None
    # Ollama offline -> None (graceful degrade).
    assert LaneCoach(FakeEngine(available=False)).plan(ctx, matchup, intel) is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
