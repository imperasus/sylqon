"""Offline tests for the rank-band × role benchmark table (data/benchmarks.py)
and the analytical grounding it feeds: role-normalized aggression and the
recent-window death baseline behind the tilt read.

Run: python -m pytest tests/test_benchmarks.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon.data import benchmarks as bm
from sylqon.lcu import scout as scout_mod


# ------------------------------------------------------------------ rank bands
def test_every_tier_maps_to_a_known_band():
    tiers = ["IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD",
             "DIAMOND", "MASTER", "GRANDMASTER", "CHALLENGER"]
    for t in tiers:
        assert bm.rank_band(t) in bm.RANK_BANDS


def test_unknown_and_unranked_fall_back_to_default_band():
    assert bm.rank_band(None) == bm.DEFAULT_BAND
    assert bm.rank_band("") == bm.DEFAULT_BAND
    assert bm.rank_band("UNRANKED") == bm.DEFAULT_BAND
    assert bm.rank_band("nonsense") == bm.DEFAULT_BAND


def test_rank_band_is_case_insensitive():
    assert bm.rank_band("gold") == bm.rank_band("GOLD")


# ------------------------------------------------------------------- the table
def test_table_is_complete_for_every_band_and_role():
    metrics = {"cs_per_min", "kills_assists", "deaths", "vision_score"}
    for band in bm.RANK_BANDS:
        assert band in bm.BENCHMARKS, band
        for role in bm.ROLES:
            row = bm.BENCHMARKS[band][role]
            assert metrics <= set(row), (band, role)
            assert all(isinstance(v, (int, float)) for v in row.values())


def test_cs_target_rises_with_rank():
    """The whole point of the table: a Gold laner is not graded against apex farm."""
    for role in ("top", "jungle", "middle", "bottom"):
        targets = [bm.BENCHMARKS[b][role]["cs_per_min"] for b in bm.RANK_BANDS]
        assert targets == sorted(targets), role
        assert targets[0] < targets[-1], role


def test_support_cs_bar_stays_low():
    """Supports farm by design — their CS bar must never approach a laner's."""
    for band in bm.RANK_BANDS:
        assert bm.BENCHMARKS[band]["utility"]["cs_per_min"] < 2.0


def test_vision_is_highest_for_support():
    for band in bm.RANK_BANDS:
        row = bm.BENCHMARKS[band]
        assert row["utility"]["vision_score"] == max(
            r["vision_score"] for r in row.values())


# --------------------------------------------------------------- the accessors
def test_cs_per_min_target_is_rank_adaptive():
    gold = bm.cs_per_min_target("bottom", "GOLD")
    chall = bm.cs_per_min_target("bottom", "CHALLENGER")
    assert chall > gold


def test_benchmark_unknown_role_falls_back_to_mid_profile():
    assert bm.benchmark("nonsense", "GOLD") == bm.BENCHMARKS[bm.rank_band("GOLD")]["middle"]


def test_as_dict_is_json_safe_and_complete():
    import json
    payload = bm.as_dict()
    assert set(payload) == {"roles", "bands", "default_band", "tier_to_band", "table"}
    json.loads(json.dumps(payload))  # must serialize cleanly for /api/benchmarks
    assert payload["default_band"] in payload["bands"]


# ------------------------------------------------ role-normalized aggression
def _kda(kills, deaths, assists):
    return {"kills": kills, "deaths": deaths, "assists": assists,
            "ratio": round((kills + assists) / max(deaths, 1), 2)}


def test_support_assists_no_longer_read_as_max_aggression():
    """A support on 2/5/14 is doing its job, not playing hyper-aggressively —
    the role-normalized K+A denominator is what keeps this honest."""
    supp = scout_mod._aggression_score(_kda(2, 5, 14), 1.0, "utility")
    top = scout_mod._aggression_score(_kda(2, 5, 14), 1.0, "top")
    assert supp < top  # same line, higher bar for the assist-heavy role


def test_aggression_still_rises_with_kills_and_deaths():
    calm = scout_mod._aggression_score(_kda(2, 2, 3), 7.0, "middle")
    wild = scout_mod._aggression_score(_kda(9, 9, 8), 7.0, "middle")
    assert wild > calm


def test_aggression_stays_in_unit_range():
    for role in list(bm.ROLES) + ["", "unknown"]:
        for k, d, a in [(0, 0, 0), (20, 20, 20), (1, 0, 30)]:
            score = scout_mod._aggression_score(_kda(k, d, a), 8.0, role)
            assert 0.0 <= score <= 1.0


def test_involvement_norm_covers_every_role():
    for role in bm.ROLES:
        assert role in scout_mod.INVOLVEMENT_KA_BY_ROLE


# ------------------------------------------- recent-window death baseline
def _game(result, deaths):
    return {"result": result, "kda": {"kills": 1, "deaths": deaths, "assists": 1},
            "champion_id": 1, "role": "middle",
            "stats": {"cs_per_min": 6.0, "duration": 1800, "damage_taken": 10000,
                      "vision_score": 20}}


def test_recent_form_reports_avg_deaths():
    games = [_game("Loss", 8), _game("Loss", 6), _game("Loss", 10)]
    form = scout_mod._recent_form(games)
    assert form["streak"] == -3
    assert form["avg_deaths"] == 8.0


def test_recent_form_empty_is_zeroed_not_missing():
    form = scout_mod._recent_form([])
    assert form["avg_deaths"] == 0.0
    assert form["games"] == 0


def test_fingerprint_exposes_avg_deaths_for_the_tilt_read():
    games = [_game("Loss", 9) for _ in range(5)]
    fp = scout_mod.fingerprint(games)
    assert fp.recent_form["avg_deaths"] == 9.0
