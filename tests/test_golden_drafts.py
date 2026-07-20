"""F6 — closed-loop draft eval: golden scenarios + engine invariants.

Mirrors the loadout-side ``test_golden_loadouts`` / ``test_loadout_invariants``
pattern for the draft engine. The golden cases pin the read on canonical drafts
(so a future change that shifts a verdict is caught), and the invariants assert
properties that must hold for *every* draft (bounds, label/pct consistency,
confidence monotonicity, tempo symmetry).
"""
from __future__ import annotations

from sylqon.analysis import draft_intel, power_curve, win_model
from sylqon.lcu.lobby import summarize_team


def _pick(name, dmg="AP", tags=(), threats=()):
    return {"name": name, "damage_type": dmg, "tags": list(tags), "threats": list(threats)}


def _balance(ally, enemy, **kw):
    return draft_intel.draft_balance(
        draft_intel.classify_comp(ally), draft_intel.classify_comp(enemy),
        summarize_team(ally), summarize_team(enemy), **kw)


# Canonical comps ------------------------------------------------------------
_ENGAGE = [
    _pick("Leona", "AP", ["Tank", "Support"], ["heavy_cc"]),
    _pick("Malphite", "AP", ["Tank"], ["heavy_cc", "tank"]),
    _pick("Sejuani", "AD", ["Tank", "Fighter"], ["heavy_cc", "tank"]),
]
_POKE = [
    _pick("Xerath", "AP", ["Mage"], ["poke", "burst_ap"]),
    _pick("Varus", "AP", ["Marksman"], ["poke"]),
    _pick("Ziggs", "AP", ["Mage"], ["poke"]),
]
_SCALING = [_pick("Jinx", "AD", ["Marksman"]), _pick("Kayle", "AD", ["Fighter"]),
            _pick("Kassadin", "AP", ["Assassin"])]
_EARLY = [_pick("Draven", "AD", ["Marksman"]), _pick("Renekton", "AD", ["Fighter"]),
          _pick("Pantheon", "AD", ["Fighter"])]


# -- golden verdicts ---------------------------------------------------------
def test_golden_engage_beats_poke():
    out = _balance(_ENGAGE, _POKE)
    assert out["label"] == "FAVOURED" and out["win_pct"] > 55


def test_golden_poke_loses_to_engage():
    out = _balance(_POKE, _ENGAGE)
    assert out["label"] == "BEHIND" and out["win_pct"] < 45


def test_golden_mirror_is_even():
    out = _balance(_ENGAGE, list(_ENGAGE))
    assert out["label"] == "EVEN"


def test_golden_scaling_vs_early_tempo():
    assert power_curve.tempo_read(_SCALING, _EARLY)["sign"] == 1
    assert power_curve.tempo_read(_EARLY, _SCALING)["sign"] == -1


# -- engine invariants (must hold for every draft) ---------------------------
_DRAFTS = [(_ENGAGE, _POKE), (_POKE, _ENGAGE), (_SCALING, _EARLY),
           (_ENGAGE, _ENGAGE), (_SCALING, _POKE), ([_pick("Ahri")], [_pick("Zed")])]


def test_invariant_win_pct_within_model_band():
    for ally, enemy in _DRAFTS:
        wp = _balance(ally, enemy)["win_pct"]
        assert win_model.WIN_PCT_FLOOR <= wp <= win_model.WIN_PCT_CEIL


def test_invariant_label_matches_win_pct():
    for ally, enemy in _DRAFTS:
        out = _balance(ally, enemy)
        if out["label"] == "FAVOURED":
            assert out["win_pct"] >= 55
        elif out["label"] == "BEHIND":
            assert out["win_pct"] <= 45
        else:
            assert 45 < out["win_pct"] < 55


def test_invariant_confidence_bounded_and_grows_with_reveals():
    sparse = _balance([_pick("Ahri")], [_pick("Zed")])
    full = _balance(_ENGAGE, _POKE)
    assert 0 <= sparse["confidence"] <= 100
    assert 0 <= full["confidence"] <= 100
    assert full["confidence"] >= sparse["confidence"]  # more revealed => surer


def test_invariant_tempo_read_is_antisymmetric():
    for ally, enemy in _DRAFTS:
        a = power_curve.tempo_read(ally, enemy)["sign"]
        b = power_curve.tempo_read(enemy, ally)["sign"]
        assert a == -b   # swapping sides flips (or keeps 0) the tempo verdict


def test_invariant_favoured_never_contradicts_drivers():
    # A FAVOURED read must carry at least one positive driver (no unexplained edge).
    for ally, enemy in _DRAFTS:
        out = _balance(ally, enemy)
        if out["label"] == "FAVOURED":
            assert any(d["sign"] == 1 for d in out["drivers"])
