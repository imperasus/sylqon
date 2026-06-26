"""Offline tests for the deterministic head-to-head draft balance.

Covers :func:`sylqon.analysis.draft_intel.draft_balance` — the estimated win%
that the draft scorecard surfaces in the live draft and post-lock views. Pure
function, no LCU / DB / Ollama.

Run: python -m pytest tests/test_draft_balance.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon.analysis import draft_intel
from sylqon.lcu.lobby import summarize_team


def _pick(name, dmg="AP", tags=(), threats=()):
    """Plain dict pick, the shape both classify_comp and summarize_team accept."""
    return {"name": name, "damage_type": dmg, "tags": list(tags), "threats": list(threats)}


def _balance(ally, enemy, **kw):
    return draft_intel.draft_balance(
        draft_intel.classify_comp(ally), draft_intel.classify_comp(enemy),
        summarize_team(ally), summarize_team(enemy), **kw)


# Reusable comps -------------------------------------------------------------
def _engage():
    return [
        _pick("Leona", dmg="AP", tags=["Tank", "Support"], threats=["heavy_cc"]),
        _pick("Malphite", dmg="AP", tags=["Tank"], threats=["heavy_cc", "tank"]),
        _pick("Sejuani", dmg="AD", tags=["Tank", "Fighter"], threats=["heavy_cc", "tank"]),
    ]


def _poke():
    return [
        _pick("Xerath", dmg="AP", tags=["Mage"], threats=["poke", "burst_ap"]),
        _pick("Varus", dmg="AP", tags=["Marksman"], threats=["poke"]),
        _pick("Ziggs", dmg="AP", tags=["Mage"], threats=["poke"]),
    ]


# -- core behaviour ----------------------------------------------------------
def test_archetype_clash_favours_engage_into_poke():
    out = _balance(_engage(), _poke())
    assert out["win_pct"] > 55
    assert out["label"] == "FAVOURED"
    assert out["tone"] == "good"
    assert any(d["sign"] == 1 for d in out["drivers"])


def test_mono_damage_enemy_helps_you():
    # Enemy is pure AP (a single MR item answers them); you bring mixed damage.
    ally = [_pick("Jinx", dmg="AD", tags=["Marksman"]),
            _pick("Orianna", dmg="AP", tags=["Mage"]),
            _pick("Ornn", dmg="AD", tags=["Tank", "Fighter"], threats=["tank"])]
    out = _balance(ally, _poke())
    assert out["win_pct"] > 50
    texts = [d["text"] for d in out["drivers"]]
    assert "Enemy mono-damage" in texts or "Mixed damage" in texts


def test_no_frontline_is_penalised():
    # Mixed damage but zero frontline (no Tank/Fighter) -> structural liability.
    ally = [_pick("Jinx", dmg="AD", tags=["Marksman"]),
            _pick("Orianna", dmg="AP", tags=["Mage"]),
            _pick("Syndra", dmg="AP", tags=["Mage"])]
    enemy = [_pick("Ornn", dmg="AD", tags=["Tank", "Fighter"], threats=["tank"]),
             _pick("Garen", dmg="AD", tags=["Fighter"]),
             _pick("Lux", dmg="AP", tags=["Mage"])]
    out = _balance(ally, enemy)
    assert out["win_pct"] < 50
    assert any(d["text"] == "No frontline" and d["sign"] == -1 for d in out["drivers"])


def test_symmetric_comps_stay_near_even():
    out = _balance(_engage(), _engage())
    assert 45 <= out["win_pct"] <= 55


def test_win_pct_clamped_to_band():
    # Pile on every positive signal incl. a maxed lane lead -> capped at the ceil.
    hi = _balance(_engage(), _poke(), lane_advantage=10)
    assert hi["win_pct"] == 65
    # Mirror it -> capped at the floor.
    lo = _balance(_poke(), _engage(), lane_advantage=-10)
    assert lo["win_pct"] == 35


def test_sparse_draft_is_low_confidence_and_even():
    out = _balance([_pick("Ahri")], [_pick("Zed", dmg="AD", tags=["Assassin"])])
    assert out["win_pct"] == 50
    assert out["confidence"] < 50


def test_drivers_are_signed_and_capped():
    out = _balance(_engage(), _poke(), lane_advantage=8)
    assert len(out["drivers"]) <= 4
    for d in out["drivers"]:
        assert set(d) == {"text", "sign"}
        assert d["sign"] in (1, -1)


def test_handles_missing_inputs_gracefully():
    out = draft_intel.draft_balance({}, {}, {}, {})
    assert out["win_pct"] == 50
    assert out["drivers"] == []
    assert out["label"] == "EVEN"
