"""Offline tests for the lane-matchup edge blend (analysis/lane_matchup.py).

Covers each signal in isolation (champion matchup, form, rank, experience), the
confidence gating that keeps thin data honest, and the aggregate blend. Pure —
no DB, LCU or network; the champion-matchup lookup is injected as a stub.

Run: python -m pytest tests/test_lane_matchup.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon.analysis import lane_matchup as lm

ROLES = ["top", "jungle", "middle", "bottom", "utility"]


def _mu(advantage, games=None):
    """A matchup_fn stub returning a fixed advantage/sample for any pairing."""
    def fn(a_cid, e_cid, role):
        return {"advantage": advantage, "games": games}
    return fn


def _none_mu(a_cid, e_cid, role):
    return None


# --------------------------------------------------------------- champion matchup
def test_matchup_only_favors_ally():
    ally = {"champion_id": 1, "champion": "Renekton", "role": "top"}
    enemy = {"champion_id": 2, "champion": "Kayle", "role": "top"}
    res = lm.lane_edge(ally, enemy, _mu(3.0, games=1200))
    assert res["edge"] > 0
    assert res["lean"] == "ally"
    assert any("Renekton" in r for r in res["reasons"])


def test_matchup_only_favors_enemy():
    ally = {"champion_id": 1, "champion": "Kayle", "role": "top"}
    enemy = {"champion_id": 2, "champion": "Renekton", "role": "top"}
    res = lm.lane_edge(ally, enemy, _mu(-3.0, games=1200))
    assert res["edge"] < 0
    assert res["lean"] == "enemy"


def test_matchup_missing_row_is_low_data_even():
    ally = {"champion_id": 1, "champion": "Ahri", "role": "middle"}
    enemy = {"champion_id": 2, "champion": "Zed", "role": "middle"}
    res = lm.lane_edge(ally, enemy, _none_mu)
    assert res["lean"] == "even"
    assert res["low_data"] is True
    assert res["confidence"] == 0.0


def test_matchup_confidence_scales_with_sample():
    ally = {"champion_id": 1, "champion": "A", "role": "top"}
    enemy = {"champion_id": 2, "champion": "B", "role": "top"}
    small = lm.lane_edge(ally, enemy, _mu(3.0, games=40))
    large = lm.lane_edge(ally, enemy, _mu(3.0, games=1200))
    assert large["confidence"] > small["confidence"]


def test_matchup_unknown_games_uses_default_conf():
    ally = {"champion_id": 1, "champion": "A", "role": "top"}
    enemy = {"champion_id": 2, "champion": "B", "role": "top"}
    res = lm.lane_edge(ally, enemy, _mu(4.0, games=None))
    cw = lm.W_MATCHUP * lm.MATCHUP_NO_GAMES_CONF          # evidence mass
    assert abs(res["confidence"] - cw / (cw + lm.CONF_SATURATION)) < 1e-6


# ------------------------------------------------------------------------- form
def test_form_shrinks_small_streaks():
    # A 3-0 ally vs a matchup-less lane must NOT read as a strong ally edge:
    # the shrink pulls 100%/3g toward the mean, and one-sided form is faint.
    ally = {"champion_id": 1, "recent_form": {"games": 3, "win_rate": 1.0}, "role": "top"}
    enemy = {"champion_id": 2, "role": "top"}
    res = lm.lane_edge(ally, enemy, _none_mu)
    assert res["lean"] == "even"  # too little to call


def test_form_two_sided_delta():
    ally = {"champion_id": 1, "name": "Ally", "recent_form": {"games": 20, "win_rate": 0.75}, "role": "top"}
    enemy = {"champion_id": 2, "name": "Enemy", "recent_form": {"games": 20, "win_rate": 0.30}, "role": "top"}
    res = lm.lane_edge(ally, enemy, _none_mu)
    assert res["edge"] > 0
    assert res["lean"] == "ally"
    assert any("form" in r for r in res["reasons"])


# ------------------------------------------------------------------------- rank
def test_rank_delta_favors_higher():
    ally = {"champion_id": 1, "name": "Ally", "rank": {"tier": "DIAMOND", "division": "II", "label": "D2"}, "role": "top"}
    enemy = {"champion_id": 2, "name": "Enemy", "rank": {"tier": "GOLD", "division": "IV", "label": "G4"}, "role": "top"}
    res = lm.lane_edge(ally, enemy, _none_mu)
    assert res["edge"] > 0
    assert res["lean"] == "ally"


def test_rank_steps_ordering():
    assert lm._rank_steps({"tier": "GOLD", "division": "IV"}) < lm._rank_steps({"tier": "GOLD", "division": "I"})
    assert lm._rank_steps({"tier": "GOLD", "division": "I"}) < lm._rank_steps({"tier": "PLATINUM", "division": "IV"})
    assert lm._rank_steps({"tier": "CHALLENGER", "division": ""}) > lm._rank_steps({"tier": "DIAMOND", "division": "I"})
    assert lm._rank_steps(None) is None
    assert lm._rank_steps({"tier": "UNRANKED"}) is None


# ------------------------------------------------------------------- experience
def test_experience_delta_rewards_practice():
    ally = {"champion_id": 1, "name": "Main", "champion": "Yasuo",
            "current_champ": {"games": 60, "win_rate": 0.58}, "role": "middle"}
    enemy = {"champion_id": 2, "name": "First", "champion": "Yone",
             "current_champ": {"games": 2, "win_rate": 0.50}, "role": "middle"}
    res = lm.lane_edge(ally, enemy, _none_mu)
    assert res["edge"] > 0


# ------------------------------------------------------------- aggregate + blend
def test_matchup_outweighs_a_faint_contrary_form():
    # Strong, well-sampled champion counter for the ally; enemy slightly hotter.
    ally = {"champion_id": 1, "champion": "Renekton", "name": "A",
            "recent_form": {"games": 10, "win_rate": 0.4}, "role": "top"}
    enemy = {"champion_id": 2, "champion": "Kayle", "name": "B",
             "recent_form": {"games": 10, "win_rate": 0.6}, "role": "top"}
    res = lm.lane_edge(ally, enemy, _mu(4.0, games=1500))
    assert res["lean"] == "ally"  # the counter dominates the weak form wobble


def test_all_signals_stack():
    ally = {"champion_id": 1, "champion": "Renekton", "name": "A",
            "recent_form": {"games": 20, "win_rate": 0.7},
            "rank": {"tier": "DIAMOND", "division": "I", "label": "D1"},
            "current_champ": {"games": 80, "win_rate": 0.6}, "role": "top"}
    enemy = {"champion_id": 2, "champion": "Kayle", "name": "B",
             "recent_form": {"games": 20, "win_rate": 0.3},
             "rank": {"tier": "PLATINUM", "division": "IV", "label": "P4"},
             "current_champ": {"games": 5, "win_rate": 0.4}, "role": "top"}
    res = lm.lane_edge(ally, enemy, _mu(3.0, games=1000))
    assert res["lean"] == "ally"
    assert res["confidence"] > 0.6   # all four signals present and confident
    assert len(res["reasons"]) <= lm.MAX_REASONS


def test_edge_stays_in_range():
    ally = {"champion_id": 1, "champion": "A", "name": "A",
            "recent_form": {"games": 30, "win_rate": 1.0},
            "rank": {"tier": "CHALLENGER", "division": "", "label": "C"},
            "current_champ": {"games": 300, "win_rate": 1.0}, "role": "top"}
    enemy = {"champion_id": 2, "champion": "B", "name": "B",
             "recent_form": {"games": 30, "win_rate": 0.0},
             "rank": {"tier": "IRON", "division": "IV", "label": "I4"},
             "current_champ": {"games": 1, "win_rate": 0.0}, "role": "top"}
    res = lm.lane_edge(ally, enemy, _mu(10.0, games=5000))
    assert -1.0 <= res["edge"] <= 1.0
    assert 0.0 <= res["confidence"] <= 1.0


def test_compute_lanes_skips_empty_roles():
    ally_by_role = {"top": {"champion_id": 1, "champion": "A", "role": "top"}}
    enemy_by_role = {"top": {"champion_id": 2, "champion": "B", "role": "top"}}
    out = lm.compute_lanes(ally_by_role, enemy_by_role, _mu(2.0, games=500), ROLES)
    assert set(out) == {"top"}   # only the populated lane


def test_empty_inputs_are_even():
    res = lm.lane_edge(None, None, _none_mu)
    assert res["lean"] == "even"
    assert res["confidence"] == 0.0
    assert res["reasons"] == []
