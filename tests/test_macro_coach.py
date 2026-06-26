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

from sylqon.analysis import macro_coach
from sylqon.ai.macro_coach_prompt import MacroCoachAnalyzer


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
