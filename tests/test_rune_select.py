"""Offline tests for the deterministic matchup rune-page selector
(analysis/rune_select.py) and its op.gg payload plumbing.

Run: python -m pytest tests/test_rune_select.py -q
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon.analysis import rune_select
from sylqon.lcu.lobby import EnemyProfile, MatchContext


def _ctx(enemies=None, champion="Syndra", role="middle") -> MatchContext:
    return MatchContext(
        summoner_id=1, my_champion=champion, my_champion_id=1, my_role=role,
        locked=True, all_locked=True, my_turn=False, enemies=enemies or [],
        allies=[], fingerprint="fp",
    )


def _enemy(name, **kw) -> EnemyProfile:
    defaults = dict(champion_id=1, role="middle", side="enemy",
                    damage_type="AP", tags=[], threats=[])
    defaults.update(kw)
    return EnemyProfile(name=name, **defaults)


# Meta page: Electrocute, no defensive secondary (no counter-tag runes).
_META_PAGE = {
    "keystone": "Electrocute",
    "primary_runes": ["Cheap Shot", "Eyeball Collection", "Ultimate Hunter"],
    "secondary_style": "Sorcery",
    "secondary_runes": ["Manaflow Band", "Transcendence"],
    "stat_shards": ["Adaptive Force", "Adaptive Force", "Health"],
}

# Challenger page: same keystone but a Resolve secondary carrying Nullifying Orb
# (magic_shield) + Bone Plating (anti_burst).
_DEF_PAGE = {
    "keystone": "Electrocute",
    "primary_runes": ["Cheap Shot", "Eyeball Collection", "Ultimate Hunter"],
    "secondary_style": "Resolve",
    "secondary_runes": ["Nullifying Orb", "Bone Plating"],
    "stat_shards": ["Adaptive Force", "Adaptive Force", "Health"],
}


def _candidate(options):
    cand = copy.deepcopy(_META_PAGE)
    cand["rune_page_options"] = options
    return cand


def _opt(page, games, wr):
    o = copy.deepcopy(page)
    o["games"] = games
    o["win_rate"] = wr
    return o


def _burst_ctx():
    return _ctx([_enemy("Syndra", threats=["burst_ap"]),
                 _enemy("Zed", damage_type="AD", threats=["burst_ad"])])


# ---------------------------------------------------------------------------
# rune_requirements
# ---------------------------------------------------------------------------

class TestRuneRequirements:
    def test_ap_burst_needs_magic_shield(self):
        assert "magic_shield" in rune_select.rune_requirements(
            _ctx([_enemy("LeBlanc", threats=["burst_ap"])]))

    def test_ad_burst_needs_anti_burst(self):
        assert "anti_burst" in rune_select.rune_requirements(
            _ctx([_enemy("Zed", damage_type="AD", threats=["burst_ad"])]))

    def test_double_poke_needs_anti_poke(self):
        reqs = rune_select.rune_requirements(
            _ctx([_enemy("Xerath", threats=["poke"]),
                  _enemy("Ziggs", threats=["poke"])]))
        assert "anti_poke" in reqs

    def test_balanced_comp_no_reqs(self):
        assert rune_select.rune_requirements(_ctx([_enemy("Ahri")])) == set()


# ---------------------------------------------------------------------------
# select_rune_page
# ---------------------------------------------------------------------------

class TestSelectRunePage:
    def test_burst_comp_swaps_to_defensive_page(self):
        cand = _candidate([_opt(_META_PAGE, 1200, 0.51),
                           _opt(_DEF_PAGE, 400, 0.52)])
        page, reason = rune_select.select_rune_page(cand, _burst_ctx())
        assert page is not None
        assert page["secondary_runes"] == ["Nullifying Orb", "Bone Plating"]
        assert "400 games" in reason

    def test_balanced_comp_keeps_meta(self):
        cand = _candidate([_opt(_META_PAGE, 1200, 0.51),
                           _opt(_DEF_PAGE, 400, 0.52)])
        page, reason = rune_select.select_rune_page(cand, _ctx([_enemy("Ahri")]))
        assert page is None and reason == ""

    def test_sample_floor_keeps_meta(self):
        cand = _candidate([_opt(_META_PAGE, 1200, 0.51),
                           _opt(_DEF_PAGE, 5, 0.52)])
        page, _ = rune_select.select_rune_page(cand, _burst_ctx())
        assert page is None

    def test_confidently_worse_page_keeps_meta(self):
        cand = _candidate([_opt(_META_PAGE, 1900, 0.56),
                           _opt(_DEF_PAGE, 300, 0.40)])
        page, _ = rune_select.select_rune_page(cand, _burst_ctx())
        assert page is None

    def test_no_extra_coverage_keeps_meta(self):
        # Challenger has a Resolve secondary but no counter-tag runes.
        plain = copy.deepcopy(_DEF_PAGE)
        plain["secondary_runes"] = ["Conditioning", "Overgrowth"]  # resist_scaling only
        cand = _candidate([_opt(_META_PAGE, 1200, 0.51),
                           _opt(plain, 400, 0.52)])
        # A pure AP-burst comp mandates magic_shield, which 'plain' lacks.
        page, _ = rune_select.select_rune_page(
            cand, _ctx([_enemy("LeBlanc", threats=["burst_ap"])]))
        assert page is None

    def test_single_option_keeps_meta(self):
        cand = _candidate([_opt(_META_PAGE, 1200, 0.51)])
        assert rune_select.select_rune_page(cand, _burst_ctx())[0] is None


class TestApplyRuneSelection:
    def test_apply_folds_page_and_preserves_original(self):
        cand = _candidate([_opt(_META_PAGE, 1200, 0.51),
                           _opt(_DEF_PAGE, 400, 0.52)])
        before = copy.deepcopy(cand)
        out = rune_select.apply_rune_selection(cand, _burst_ctx())
        assert out is not cand and cand == before
        assert out["secondary_style"] == "Resolve"
        assert out["secondary_runes"] == ["Nullifying Orb", "Bone Plating"]
        assert "runes" in out["rune_reason"]

    def test_apply_noop_returns_same_object(self):
        cand = _candidate([_opt(_META_PAGE, 1200, 0.51),
                           _opt(_DEF_PAGE, 400, 0.52)])
        assert rune_select.apply_rune_selection(cand, _ctx([_enemy("Ahri")])) is cand


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
