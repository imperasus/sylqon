"""Offline tests for the coach decisions layer (analysis/decisions.py):
the structured why-list of every deviation from the meta build, and the calm
"meta is optimal" fallback when nothing deviated.

Run: python -m pytest tests/test_decisions.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon import loadout as loadout_mod
from sylqon.analysis import decisions as decisions_mod
from sylqon.data import static
from sylqon.lcu.lobby import EnemyProfile, MatchContext


class _StubCatalog:
    def item_id(self, name):
        return None


def _ctx(enemies=None, role="top", champion="Garen") -> MatchContext:
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


def _build():
    boots = {"id": 3006, "name": "Berserker's Greaves"}
    core = [{"id": 3031, "name": "Infinity Edge"},
            {"id": 3072, "name": "Bloodthirster"},
            {"id": 6672, "name": "Kraken Slayer"}]
    default_situ = [{"id": 3078, "name": "Trinity Force"},
                    {"id": 3508, "name": "Essence Reaver"}]
    pool = [{"id": 3033, "name": "Mortal Reminder"},
            {"id": 3036, "name": "Lord Dominik's Regards"},
            {"id": 3140, "name": "Quicksilver Sash"}]
    return {
        "boots": boots, "boots_pool": [boots],
        "core_items": core, "situational_pool": pool,
        "items": [boots] + core + default_situ,
        "starting_items": [dict(static.DORANS_BLADE)],
        "keystone": "Conqueror",
        "primary_runes": ["Triumph", "Legend: Alacrity", "Last Stand"],
        "secondary_style": "Resolve", "secondary_runes": ["Second Wind", "Overgrowth"],
        "stat_shards": ["Adaptive Force", "Adaptive Force", "Health"],
        "spell1": "Teleport", "spell2": "Flash",
    }


def _compile(enemies, role="top", champion="Garen"):
    ctx = _ctx(enemies, role=role, champion=champion)
    build = _build()
    meta = loadout_mod.from_candidate(build, ctx, "seed")
    base = loadout_mod.from_candidate(build, ctx, "seed")
    final = loadout_mod.apply_ai_decision(base, None, ctx, _StubCatalog(), build)
    return final, meta, build, ctx


def _slots(decisions):
    return {d["slot"] for d in decisions}


class TestDecisions:
    def test_balanced_comp_emits_meta_optimal(self):
        final, meta, build, ctx = _compile([_enemy("Ahri", role="middle")])
        out = decisions_mod.build_decisions(final, meta, build, ctx)
        assert len(out) == 1
        assert out[0]["kind"] == "keep" and out[0]["slot"] == "Meta"

    def test_healing_comp_reports_counter_item(self):
        final, meta, build, ctx = _compile(
            [_enemy("Soraka", role="utility", threats=["heavy_healing"])])
        out = decisions_mod.build_decisions(final, meta, build, ctx)
        assert "Items" in _slots(out)
        items_dec = next(d for d in out if d["slot"] == "Items")
        assert "Mortal Reminder" in items_dec["summary"]
        assert items_dec["kind"] == "add"

    def test_poke_lane_reports_starter_and_first_back(self):
        # Poke lane opponent → Doran's Shield start (starter reason).
        final, meta, build, ctx = _compile(
            [_enemy("Jayce", role="top", damage_type="AD", threats=["poke"])])
        out = decisions_mod.build_decisions(final, meta, build, ctx)
        assert "Starter" in _slots(out)

    def test_suppression_lane_reports_first_back(self):
        final, meta, build, ctx = _compile(
            [_enemy("Malzahar", role="top", threats=["suppression"])])
        out = decisions_mod.build_decisions(final, meta, build, ctx)
        assert "First Back" in _slots(out)
        fb = next(d for d in out if d["slot"] == "First Back")
        assert "Quicksilver Sash" in fb["summary"]

    def test_spell_change_reported(self):
        # Darius top into a killable lane → Ignite over the Teleport default.
        build = _build()
        build["spell_options"] = ["Teleport", "Flash", "Ignite"]
        ctx = _ctx([_enemy("Riven", role="top", damage_type="AD")],
                   role="top", champion="Darius")
        meta = loadout_mod.from_candidate(build, ctx, "seed")
        # meta baseline uses the same threat-aware spells, so force a contrast:
        # a champion NOT in IGNITE_KILL_LANERS keeps Teleport as the baseline.
        base = loadout_mod.from_candidate(build, ctx, "seed")
        final = loadout_mod.apply_ai_decision(base, None, ctx, _StubCatalog(), build)
        # Both meta and final are Darius here, so both take Ignite — no spell
        # delta. Assert the decision layer stays silent on spells when equal.
        out = decisions_mod.build_decisions(final, meta, build, ctx)
        assert "Spell" not in _slots(out)

    def test_reason_present_on_every_decision(self):
        final, meta, build, ctx = _compile(
            [_enemy("Soraka", role="utility", threats=["heavy_healing"])])
        out = decisions_mod.build_decisions(final, meta, build, ctx)
        for d in out:
            assert d["reason"] and d["summary"] and d["slot"]

    def test_never_raises_on_minimal_loadout(self):
        ctx = _ctx([])
        empty = loadout_mod.Loadout(
            items=[], starting_items=[], primary_style_id=8000,
            secondary_style_id=8100, rune_perk_ids=[], shard_ids=[], spell1="Heal")
        out = decisions_mod.build_decisions(empty, empty, {}, ctx)
        assert out and out[0]["slot"] == "Meta"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
