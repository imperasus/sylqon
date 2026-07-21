"""Offline tests for the AI Macro Coach (feature A).

Covers the deterministic scorecard (`analysis.macro_coach.build_scorecard`) and
the LLM synthesis layer (`ai.macro_coach_prompt.MacroCoachAnalyzer`) with a fake
engine. No LCU / DB / Ollama / network.

Run: python -m pytest tests/test_macro_coach.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon.ai.macro_coach_prompt import MacroCoachAnalyzer
from sylqon.analysis import macro_coach


def _match(*, role="bottom", result="Win", cs_min=8.0, vision=25, deaths=3,
           kills=8, assists=6, dmg=25000, dur=1800):
    return {
        "result": result, "role": role,
        "kda": {"kills": kills, "deaths": deaths, "assists": assists},
        "stats": {"duration": dur, "cs_per_min": cs_min, "vision_score": vision,
                  "total_damage": dmg},
    }


def _dim(sc, key):
    return next(d for d in sc["dimensions"] if d["key"] == key)


# -- scorecard ---------------------------------------------------------------
def test_empty_history_is_insufficient():
    sc = macro_coach.build_scorecard([])
    assert sc["games_analyzed"] == 0
    assert sc["insufficient"] is True
    assert sc["win_rate"] is None
    assert {d["key"] for d in sc["dimensions"]} == {"farm", "vision", "combat", "survival"}


def test_high_vs_low_farm_score():
    hi = macro_coach.build_scorecard([_match(cs_min=9.0) for _ in range(5)])
    lo = macro_coach.build_scorecard([_match(cs_min=3.0) for _ in range(5)])
    assert _dim(hi, "farm")["score"] > _dim(lo, "farm")["score"]
    assert _dim(hi, "farm")["score"] >= 50  # 9.0 cs/min for ADC is strong


def test_many_deaths_tanks_survival():
    feeding = macro_coach.build_scorecard([_match(deaths=12) for _ in range(5)])
    clean = macro_coach.build_scorecard([_match(deaths=2) for _ in range(5)])
    assert _dim(feeding, "survival")["score"] < _dim(clean, "survival")["score"]
    assert _dim(feeding, "survival")["score"] < 40


def test_role_aware_baseline_for_farm():
    # 1.6 CS/min is normal for a support but terrible for an ADC.
    sup = macro_coach.build_scorecard([_match(role="utility", cs_min=1.6) for _ in range(5)])
    adc = macro_coach.build_scorecard([_match(role="bottom", cs_min=1.6) for _ in range(5)])
    assert _dim(sup, "farm")["score"] > _dim(adc, "farm")["score"]
    assert _dim(sup, "farm")["score"] >= 50


def test_trend_up_when_recent_games_improve():
    # Newest first: 4 strong recent games, 4 weak older ones.
    games = [_match(cs_min=9.0) for _ in range(4)] + [_match(cs_min=3.0) for _ in range(4)]
    sc = macro_coach.build_scorecard(games)
    assert _dim(sc, "farm")["trend"]["dir"] == "up"
    assert _dim(sc, "farm")["trend"]["delta"] > 0


def test_win_rate_and_recent_results():
    games = [_match(result="Win"), _match(result="Loss"), _match(result="Win")]
    sc = macro_coach.build_scorecard(games)
    assert sc["win_rate"] == round(2 / 3, 3)
    assert sc["recent_results"] == ["W", "L", "W"]
    assert 0 <= sc["overall"] <= 100


def test_window_caps_games():
    sc = macro_coach.build_scorecard([_match() for _ in range(40)], window=20)
    assert sc["games_analyzed"] == 20


# -- analyzer ----------------------------------------------------------------
class FakeEngine:
    def __init__(self, available=True, response=None):
        self._a, self._r = available, response

    def available(self):
        return self._a

    def evaluate(self, prompt, options=None):
        return self._r


def test_analyzer_parses_and_clips_priorities():
    sc = macro_coach.build_scorecard([_match() for _ in range(5)])
    engine = FakeEngine(response={
        "narrative": "Stabil forma.",
        "priorities": [
            {"title": "Vízió", "detail": "Rakj több wardot."},
            {"title": "Farm", "detail": "Érd el a 8 CS/percet."},
            {"title": "Pozíció", "detail": "Kevesebb halál."},
            {"title": "Negyedik", "detail": "Ezt le kell vágni."},
        ],
    })
    out = MacroCoachAnalyzer(engine).analyze(sc)
    assert out["narrative"] == "Stabil forma."
    assert len(out["priorities"]) == 3            # clipped to 3
    assert out["priorities"][0]["title"] == "Vízió"


def test_analyzer_degrades_when_ollama_offline():
    sc = macro_coach.build_scorecard([_match() for _ in range(5)])
    assert MacroCoachAnalyzer(FakeEngine(available=False)).analyze(sc) is None


def test_analyzer_handles_garbage_response():
    sc = macro_coach.build_scorecard([_match() for _ in range(5)])
    assert MacroCoachAnalyzer(FakeEngine(response="not a dict")).analyze(sc) is None


# -- progress (movement vs the previous window) ------------------------------
def test_progress_reports_movement_between_windows():
    current = macro_coach.build_scorecard([_match(cs_min=8.0, deaths=2) for _ in range(20)])
    previous = macro_coach.build_scorecard([_match(cs_min=4.0, deaths=8) for _ in range(20)])
    p = macro_coach.build_progress(current, previous)

    assert p["available"] is True
    assert p["compared_games"] == 20
    assert p["previous_overall"] == previous["overall"]
    assert p["overall_delta"] == current["overall"] - previous["overall"]
    assert p["overall_delta"] > 0                     # strictly better window
    assert p["dimensions"]["farm"]["delta"] > 0


def test_progress_unavailable_without_a_comparable_previous_window():
    current = macro_coach.build_scorecard([_match() for _ in range(20)])
    p = macro_coach.build_progress(current, macro_coach.build_scorecard([]))

    assert p["available"] is False
    assert p["overall_delta"] is None
    # Deltas stay None rather than reading as a misleading zero.
    assert all(d["delta"] is None for d in p["dimensions"].values())


# -- goal derivation ---------------------------------------------------------
def test_goal_targets_the_weakest_dimension_with_a_reachable_step():
    sc = macro_coach.build_scorecard([_match(cs_min=3.0, vision=40, deaths=2) for _ in range(20)])
    goal = macro_coach.derive_goal(sc)

    assert goal["key"] == "farm"
    # A step up from where they are, not the ideal — an unreachable target is
    # not coaching.
    assert goal["current"] == 3.0
    assert 3.0 < goal["target"] < 6.0
    assert goal["target_score"] == goal["current_score"] + 10


def test_goal_for_survival_asks_for_fewer_deaths():
    sc = macro_coach.build_scorecard([_match(cs_min=9.0, vision=40, deaths=12) for _ in range(20)])
    goal = macro_coach.derive_goal(sc)

    assert goal["key"] == "survival"
    assert goal["target"] < goal["current"]           # lower is better here


def test_goal_is_none_without_enough_games():
    assert macro_coach.derive_goal(macro_coach.build_scorecard([])) is None
    assert macro_coach.derive_goal(macro_coach.build_scorecard([_match()])) is None


# -- rank-band baselines -----------------------------------------------------
def test_identical_games_score_differently_per_rank_band():
    games = [_match(cs_min=6.0, vision=30, deaths=5) for _ in range(20)]
    low = macro_coach.build_scorecard(games, baselines=macro_coach.rank_baselines("IRON"))
    high = macro_coach.build_scorecard(games, baselines=macro_coach.rank_baselines("MASTER"))

    # Same raw stats, harsher band -> lower score. This is the whole point of
    # grading against the player's own rank.
    assert low["overall"] > high["overall"]
    assert _dim(low, "farm")["score"] > _dim(high, "farm")["score"]


def test_rank_baselines_cover_every_role_with_the_expected_metrics():
    base = macro_coach.rank_baselines("GOLD")
    for role in ("top", "jungle", "middle", "bottom", "utility"):
        assert set(base[role]) == {"cs_min", "vis_min", "deaths", "dmg_min"}
        assert all(v > 0 for v in base[role].values())


def test_unknown_tier_falls_back_to_the_default_band():
    assert macro_coach.rank_baselines("") == macro_coach.rank_baselines("NONSENSE")


def test_primary_role_is_the_most_played_role():
    games = [_match(role="middle") for _ in range(7)] + [_match(role="top") for _ in range(3)]
    assert macro_coach.build_scorecard(games)["primary_role"] == "middle"
