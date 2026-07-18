"""Offline tests for the deterministic matchup core-combo selector
(``analysis/core_select.py``).

The selector may only deviate from the meta core when a real op.gg combo
covers strictly more mandated counter tags AND clears the sample/win-rate
guards; a balanced comp always keeps the meta combo. All synthetic — no LCU,
Ollama, or network.

Run: python -m pytest tests/test_core_select.py -q
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon.analysis import core_select
from sylqon.lcu.lobby import EnemyProfile, MatchContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _StubCatalog:
    def item_description(self, name):
        return f"{name} effect"


def _ctx(enemies=None, champion="Jinx", role="bottom") -> MatchContext:
    return MatchContext(
        summoner_id=1, my_champion=champion, my_champion_id=222, my_role=role,
        locked=True, all_locked=True, my_turn=False, enemies=enemies or [],
        allies=[], fingerprint="fp",
    )


def _enemy(name, **kw) -> EnemyProfile:
    defaults = dict(champion_id=1, role="top", side="enemy",
                    damage_type="AD", tags=[], threats=[])
    defaults.update(kw)
    return EnemyProfile(name=name, **defaults)


def _tank_ctx():
    """Two flagged tanks → urgent percent_pen/tank_shred requirement."""
    return _ctx(enemies=[
        _enemy("Ornn", threats=["tank"]),
        _enemy("Sion", threats=["tank"]),
    ])


IE = {"id": 3031, "name": "Infinity Edge"}          # no counter tag
PD = {"id": 3046, "name": "Phantom Dancer"}         # mobility (not mandated)
BT = {"id": 3072, "name": "Bloodthirster"}          # no counter tag
LDR = {"id": 3036, "name": "Lord Dominik's Regards"}  # percent_pen
VOID = {"id": 3135, "name": "Void Staff"}           # percent_pen, ap_only
GA = {"id": 3026, "name": "Guardian Angel"}         # anti_burst
BOOTS = {"id": 3006, "name": "Berserker's Greaves"}


def _candidate(core_options=None):
    """ADC build (7 items): boots + meta core [IE, PD, BT] + 3 pool picks."""
    pool = [
        {"id": LDR["id"], "name": LDR["name"], "description": "%pen"},
        {"id": GA["id"], "name": GA["name"], "description": "revive"},
        {"id": 3033, "name": "Mortal Reminder", "description": "anti-heal"},
    ]
    core = [dict(IE), dict(PD), dict(BT)]
    return {
        "boots": dict(BOOTS),
        "core_items": core,
        "core_options": core_options if core_options is not None else [],
        "situational_pool": pool,
        "items": [dict(BOOTS)] + [dict(i) for i in core]
                 + [{"id": p["id"], "name": p["name"]} for p in pool],
        "keystone": "Lethal Tempo",
    }


def _options(challenger_games=130, challenger_wr=0.63, meta_wr=0.59,
             challenger_items=(IE, PD, LDR)):
    return [
        {"items": [dict(IE), dict(PD), dict(BT)],
         "games": 1900, "win_rate": meta_wr},
        {"items": [dict(i) for i in challenger_items],
         "games": challenger_games, "win_rate": challenger_wr},
    ]


# ---------------------------------------------------------------------------
# select_core
# ---------------------------------------------------------------------------

def test_tank_comp_swaps_to_pen_combo():
    combo, reason = core_select.select_core(_candidate(_options()), _tank_ctx())
    assert combo is not None
    assert [i["name"] for i in combo["items"]] == [
        "Infinity Edge", "Phantom Dancer", "Lord Dominik's Regards"]
    assert "Anti-tank" in reason and "130 games" in reason and "63" in reason


def test_balanced_comp_keeps_meta():
    ctx = _ctx(enemies=[_enemy("Ezreal"), _enemy("Lux", damage_type="AP")])
    combo, reason = core_select.select_core(_candidate(_options()), ctx)
    assert combo is None and reason == ""


def test_sample_floor_keeps_meta():
    cand = _candidate(_options(challenger_games=10))
    combo, _ = core_select.select_core(cand, _tank_ctx())
    assert combo is None


def test_share_floor_keeps_meta():
    # 60 games but the meta combo has 10k → share < 3% → keep meta.
    opts = _options(challenger_games=60)
    opts[0]["games"] = 10_000
    combo, _ = core_select.select_core(_candidate(opts), _tank_ctx())
    assert combo is None


def test_adaptive_floor_accepts_small_source_samples():
    """The hosted Sylqon service aggregates a few dozen games, not op.gg's
    thousands — the sample floor scales down (to MIN_COMBO_GAMES_FLOOR) so a
    combo with 9 of 39 total games is still a valid challenger."""
    opts = _options(challenger_games=9)
    opts[0]["games"] = 30
    combo, reason = core_select.select_core(_candidate(opts), _tank_ctx())
    assert combo is not None
    assert "9 games" in reason


def test_win_rate_guard_keeps_meta():
    cand = _candidate(_options(challenger_wr=0.40, meta_wr=0.55))
    combo, _ = core_select.select_core(cand, _tank_ctx())
    assert combo is None


def test_type_ineligible_combo_skipped():
    # Void Staff covers percent_pen but is ap_only — never on AD Jinx.
    cand = _candidate(_options(challenger_items=(IE, PD, VOID)))
    combo, _ = core_select.select_core(cand, _tank_ctx())
    assert combo is None


def test_no_extra_coverage_keeps_meta():
    # Challenger covers nothing the comp mandates (GA is anti_burst; the
    # tank comp mandates pen) → tie on mandated coverage → meta stays.
    cand = _candidate(_options(challenger_items=(IE, PD, GA)))
    combo, _ = core_select.select_core(cand, _tank_ctx())
    assert combo is None


def test_missing_or_single_option_keeps_meta():
    assert core_select.select_core(_candidate([]), _tank_ctx())[0] is None
    only_meta = [{"items": [dict(IE), dict(PD), dict(BT)],
                  "games": 1900, "win_rate": 0.59}]
    assert core_select.select_core(_candidate(only_meta), _tank_ctx())[0] is None


# ---------------------------------------------------------------------------
# apply_core_selection
# ---------------------------------------------------------------------------

def test_apply_rebuilds_items_and_pool():
    cand = _candidate(_options())
    before = copy.deepcopy(cand)
    out = core_select.apply_core_selection(cand, _tank_ctx(), _StubCatalog())
    assert out is not cand
    assert cand == before                    # original candidate untouched
    assert [i["name"] for i in out["core_items"]] == [
        "Infinity Edge", "Phantom Dancer", "Lord Dominik's Regards"]
    # Item list invariant: same length, boots first, new core next.
    assert len(out["items"]) == len(cand["items"]) == 7
    assert out["items"][0]["name"] == "Berserker's Greaves"
    assert [i["name"] for i in out["items"][1:4]] == [
        "Infinity Edge", "Phantom Dancer", "Lord Dominik's Regards"]
    pool_names = [p["name"] for p in out["situational_pool"]]
    assert "Lord Dominik's Regards" not in pool_names   # promoted to core
    assert "Bloodthirster" in pool_names                # displaced meta core
    displaced = next(p for p in out["situational_pool"]
                     if p["name"] == "Bloodthirster")
    assert displaced.get("description")                 # pool entries carry desc
    assert "Anti-tank" in out["core_reason"]


def test_apply_noop_paths_return_same_object():
    ctx = _tank_ctx()
    cand = _candidate([])                    # no options
    assert core_select.apply_core_selection(cand, ctx, _StubCatalog()) is cand
    balanced = _ctx(enemies=[_enemy("Ezreal")])
    cand2 = _candidate(_options())           # options, but nothing mandated
    assert core_select.apply_core_selection(cand2, balanced, _StubCatalog()) is cand2
    legacy = {"items": [dict(BOOTS), dict(IE)], "core_items": [dict(IE)]}
    assert core_select.apply_core_selection(legacy, ctx, _StubCatalog()) is legacy
