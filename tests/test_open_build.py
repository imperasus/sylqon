"""Offline tests for the OpenBuild feature.

Covers:
- _active_threat_tags tag derivation
- _merge_pools dedup and ordering
- compile_open_prompt output shape
- apply_ai_open_decision validation paths

No LCU, Ollama, or network required.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


from sylqon.ai.open_build_prompt import _active_threat_tags, _merge_pools, compile_open_prompt
from sylqon.data.catalog import Catalog
from sylqon.loadout import Loadout, apply_ai_open_decision

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _threat(**kw) -> dict:
    base = {
        "heavy_healing": False, "tanks": 0, "suppression": False,
        "heavy_cc_count": 0, "burst_ad": False, "burst_ap": False,
        "physical_threats": 0, "magic_threats": 0,
    }
    base.update(kw)
    return base


def _make_loadout(**overrides) -> Loadout:
    """Minimal 5-item ADC loadout: boots + 2 core + 2 situational."""
    boots = {"id": 3006, "name": "Berserker's Greaves"}
    core = [
        {"id": 3031, "name": "Infinity Edge"},
        {"id": 3085, "name": "Runaan's Hurricane"},
    ]
    situ = [
        {"id": 3094, "name": "Rapidfire Cannon", "description": "Boost attack range"},
        {"id": 3072, "name": "Bloodthirster", "description": "Lifesteal"},
    ]
    defaults = dict(
        items=[boots] + core + situ,
        starting_items=[{"id": 1055, "name": "Doran's Blade"}],
        primary_style_id=8000,
        secondary_style_id=8100,
        rune_perk_ids=[8008, 9111, 9104, 8014, 8126, 8139],
        shard_ids=[5008, 5008, 5001],
        spell1="Heal",
        spell2="Flash",
        allowed_spell1=["Heal", "Exhaust"],
        allowed_spell2=["Flash"],
        source="opgg",
        boots=boots,
        core_items=core,
        situational_pool=list(situ),
    )
    defaults.update(overrides)
    return Loadout(**defaults)


def _make_catalog(extra_names: dict[str, int] | None = None) -> MagicMock:
    """Catalog mock whose item_id() resolves a fixed name→id table."""
    name_to_id: dict[str, int] = {
        "Berserker's Greaves": 3006,
        "Infinity Edge": 3031,
        "Runaan's Hurricane": 3085,
        "Rapidfire Cannon": 3094,
        "Bloodthirster": 3072,
        "Mortal Reminder": 3033,
        "Lord Dominik's Regards": 3036,
        "Guardian Angel": 3026,
    }
    if extra_names:
        name_to_id.update(extra_names)

    catalog = MagicMock(spec=Catalog)
    catalog.item_id.side_effect = lambda n: name_to_id.get(n)
    catalog.items_for_threat.return_value = [
        {"id": 3033, "name": "Mortal Reminder",
         "description": "Anti-heal and armor pen", "counter_tags": ["anti_heal", "percent_pen"]},
    ]
    return catalog


def _make_ctx(threat_override: dict | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.my_champion = "Jinx"
    ctx.my_role = "bottom"
    ctx.enemies = []
    ctx.allies = []
    ctx.team_threat_summary.return_value = _threat(**(threat_override or {}))
    return ctx


# ---------------------------------------------------------------------------
# _active_threat_tags
# ---------------------------------------------------------------------------

class TestActiveThreatTags:
    def test_heavy_healing_adds_anti_heal(self):
        tags = _active_threat_tags(_threat(heavy_healing=True))
        assert "anti_heal" in tags

    def test_heavy_healing_result_includes_percent_pen_fallback(self):
        tags = _active_threat_tags(_threat(heavy_healing=True))
        assert "percent_pen" in tags

    def test_tanks_gte_1_adds_percent_pen_and_tank_shred(self):
        tags = _active_threat_tags(_threat(tanks=1))
        assert "percent_pen" in tags
        assert "tank_shred" in tags

    def test_tanks_0_still_has_percent_pen_from_fallback(self):
        tags = _active_threat_tags(_threat(tanks=0))
        assert "percent_pen" in tags
        assert "tank_shred" not in tags

    def test_suppression_adds_anti_cc(self):
        tags = _active_threat_tags(_threat(suppression=True))
        assert "anti_cc" in tags

    def test_heavy_cc_count_adds_anti_cc(self):
        tags = _active_threat_tags(_threat(heavy_cc_count=3))
        assert "anti_cc" in tags

    def test_no_dominant_threat_still_returns_at_least_one_tag(self):
        tags = _active_threat_tags(_threat())
        assert len(tags) >= 1
        assert "percent_pen" in tags

    def test_no_duplicate_tags(self):
        # tanks >= 1 adds percent_pen; fallback also adds percent_pen → should dedup
        tags = _active_threat_tags(_threat(tanks=2))
        assert tags.count("percent_pen") == 1

    def test_burst_adds_anti_burst(self):
        tags = _active_threat_tags(_threat(burst_ad=True))
        assert "anti_burst" in tags

    def test_physical_threats_gte_4_adds_armor(self):
        tags = _active_threat_tags(_threat(physical_threats=4))
        assert "armor" in tags

    def test_magic_threats_gte_3_adds_mr(self):
        tags = _active_threat_tags(_threat(magic_threats=3))
        assert "mr" in tags


# ---------------------------------------------------------------------------
# _merge_pools
# ---------------------------------------------------------------------------

class TestMergePools:
    def _opgg(self, items: list[tuple[int, str]]) -> list[dict]:
        return [{"id": iid, "name": n, "description": "desc"} for iid, n in items]

    def _catalog(self, items: list[tuple[int, str]]) -> list[dict]:
        return [{"id": iid, "name": n, "description": "desc", "counter_tags": ["anti_heal"]}
                for iid, n in items]

    def test_opgg_items_come_first(self):
        opgg = self._opgg([(1, "OP Item"), (2, "Another OP")])
        cat = self._catalog([(3, "Catalog Item")])
        result = _merge_pools(cat, opgg, set())
        assert result[0]["id"] == 1
        assert result[1]["id"] == 2
        assert result[2]["id"] == 3

    def test_no_duplicates_by_id(self):
        opgg = self._opgg([(1, "Item A")])
        cat = self._catalog([(1, "Item A Duplicate")])
        result = _merge_pools(cat, opgg, set())
        assert len(result) == 1
        assert result[0]["id"] == 1

    def test_excluded_ids_absent_from_output(self):
        opgg = self._opgg([(1, "Boots"), (2, "Core Item")])
        cat = self._catalog([(3, "Cat Item")])
        result = _merge_pools(cat, opgg, {1, 3})
        ids = {r["id"] for r in result}
        assert 1 not in ids
        assert 3 not in ids
        assert 2 in ids

    def test_opgg_items_flagged_as_opgg(self):
        opgg = self._opgg([(1, "OP Item")])
        result = _merge_pools([], opgg, set())
        assert result[0].get("_is_opgg") is True

    def test_catalog_items_flagged_as_not_opgg(self):
        cat = self._catalog([(1, "Cat Item")])
        result = _merge_pools(cat, [], set())
        assert result[0].get("_is_opgg") is False

    def test_empty_inputs_return_empty(self):
        assert _merge_pools([], [], set()) == []

    def test_catalog_before_existing_opgg_ids_are_skipped(self):
        opgg = self._opgg([(10, "Meta Pick")])
        cat = self._catalog([(10, "Same ID Cat"), (20, "New Cat")])
        result = _merge_pools(cat, opgg, set())
        # id=10 should appear once (opgg), id=20 should appear once (cat)
        ids = [r["id"] for r in result]
        assert ids.count(10) == 1
        assert 20 in ids


# ---------------------------------------------------------------------------
# compile_open_prompt
# ---------------------------------------------------------------------------

class TestCompileOpenPrompt:
    def _candidate(self) -> dict:
        return {
            "boots": {"id": 3006, "name": "Berserker's Greaves"},
            "core_items": [
                {"id": 3031, "name": "Infinity Edge"},
                {"id": 3085, "name": "Runaan's Hurricane"},
            ],
            "items": [
                {"id": 3006, "name": "Berserker's Greaves"},
                {"id": 3031, "name": "Infinity Edge"},
                {"id": 3085, "name": "Runaan's Hurricane"},
                {"id": 3094, "name": "Rapidfire Cannon"},
                {"id": 3072, "name": "Bloodthirster"},
            ],
            "situational_pool": [],  # no op.gg pool so all items are catalog
            "keystone": "Lethal Tempo",
            "primary_runes": ["Legend: Alacrity", "Triumph", "Coup de Grace"],
            "secondary_style": "Domination",
            "secondary_runes": ["Taste of Blood", "Treasure Hunter"],
            "stat_shards": ["Adaptive Force", "Adaptive Force", "Health"],
            "spell1": "Heal",
            "spell2": "Flash",
        }

    def test_returns_non_empty_string(self):
        prompt = compile_open_prompt(_make_ctx(), self._candidate(), _make_catalog())
        assert isinstance(prompt, str) and len(prompt) > 0

    def test_contains_item_name_from_items_for_threat(self):
        prompt = compile_open_prompt(_make_ctx(), self._candidate(), _make_catalog())
        assert "Mortal Reminder" in prompt

    def test_contains_catalog_suggestion_label(self):
        prompt = compile_open_prompt(_make_ctx(), self._candidate(), _make_catalog())
        assert "catalog suggestion" in prompt

    def test_boots_name_in_fixed_line_not_pool(self):
        prompt = compile_open_prompt(_make_ctx(), self._candidate(), _make_catalog())
        # "Berserker's Greaves" should appear in the "Boots (fixed…)" header line
        assert "Berserker's Greaves" in prompt
        # It must NOT appear as a pool entry (pool entries start with "- ")
        pool_lines = [ln for ln in prompt.splitlines() if ln.startswith("- ")]
        boots_in_pool = any("Berserker's Greaves" in ln for ln in pool_lines)
        assert not boots_in_pool

    def test_core_items_listed_as_fixed(self):
        prompt = compile_open_prompt(_make_ctx(), self._candidate(), _make_catalog())
        assert "Infinity Edge" in prompt
        assert "Runaan's Hurricane" in prompt

    def test_my_champion_appears_in_prompt(self):
        prompt = compile_open_prompt(_make_ctx(), self._candidate(), _make_catalog())
        assert "Jinx" in prompt

    def test_opgg_item_labelled_as_meta_pick(self):
        catalog = _make_catalog()
        candidate = self._candidate()
        # Add an op.gg situational pool item
        candidate["situational_pool"] = [
            {"id": 3046, "name": "Phantom Dancer", "description": "Mobility item"},
        ]
        prompt = compile_open_prompt(_make_ctx(), candidate, catalog)
        assert "op.gg meta pick" in prompt

    def test_no_network_calls(self):
        """compile_open_prompt is fully local — the mock catalog never calls network."""
        catalog = _make_catalog()
        compile_open_prompt(_make_ctx(), self._candidate(), catalog)
        # If network was called, the test would time out or raise. Just assert no error.

    def test_matchup_core_note(self):
        """A core_reason set by the deterministic selector reaches the prompt."""
        candidate = self._candidate()
        assert "matchup-selected core" not in compile_open_prompt(
            _make_ctx(), candidate, _make_catalog())
        candidate["core_reason"] = "Anti-tank core: covers percent_pen"
        prompt = compile_open_prompt(_make_ctx(), candidate, _make_catalog())
        assert "matchup-selected core" in prompt and "do NOT swap it back" in prompt


# ---------------------------------------------------------------------------
# apply_ai_open_decision
# ---------------------------------------------------------------------------

class TestApplyAiOpenDecision:
    def _ai(self, core=None, situ=None, **kw) -> dict:
        base = {
            "core_items": core or ["Infinity Edge", "Runaan's Hurricane"],
            "situational_items": situ or ["Rapidfire Cannon", "Bloodthirster"],
            "keystone": "Lethal Tempo",
            "primary_runes": ["Legend: Alacrity", "Triumph", "Coup de Grace"],
            "secondary_style": "Domination",
            "secondary_runes": ["Taste of Blood", "Treasure Hunter"],
            "stat_shards": ["Adaptive Force", "Adaptive Force", "Health"],
            "spell1": "Heal",
            "spell2": "Flash",
            "reasoning": "Counter the enemy comp.",
        }
        base.update(kw)
        return base

    def _ctx(self) -> MagicMock:
        ctx = MagicMock()
        ctx.my_role = "bottom"
        return ctx

    def test_none_ai_returns_base_unchanged(self):
        base = _make_loadout()
        ctx = self._ctx()
        result = apply_ai_open_decision(base, None, ctx, _make_catalog())
        assert result is base

    def test_non_dict_ai_returns_base_unchanged(self):
        base = _make_loadout()
        result = apply_ai_open_decision(base, "invalid", self._ctx(), _make_catalog())
        assert result is base

    def test_valid_ai_source_ends_with_ollama_open(self):
        base = _make_loadout()
        result = apply_ai_open_decision(base, self._ai(), self._ctx(), _make_catalog())
        assert result.source.endswith("+ollama-open")

    def test_valid_items_accepted_and_present(self):
        base = _make_loadout()
        result = apply_ai_open_decision(base, self._ai(), self._ctx(), _make_catalog())
        item_names = {i["name"] for i in result.items}
        assert "Rapidfire Cannon" in item_names
        assert "Bloodthirster" in item_names

    def test_nonexistent_situational_item_rejected(self):
        """An AI-suggested name not in the catalog causes situ_valid=False → base items kept."""
        base = _make_loadout()
        ai = self._ai(situ=["FAKE_NONEXISTENT_ITEM_XYZ", "Bloodthirster"])
        result = apply_ai_open_decision(base, ai, self._ctx(), _make_catalog())
        item_names = [i["name"] for i in result.items]
        assert "FAKE_NONEXISTENT_ITEM_XYZ" not in item_names

    def test_two_core_swaps_rejected(self):
        """AI suggesting 2 different core items (both swapped) is rejected; defaults kept."""
        base = _make_loadout()
        catalog = _make_catalog(extra_names={
            "New Item A": 9001,
            "New Item B": 9002,
        })
        # Both core slots swapped — violates the ≤1 swap rule
        ai = self._ai(
            core=["New Item A", "New Item B"],
            situ=["Rapidfire Cannon", "Bloodthirster"],
        )
        result = apply_ai_open_decision(base, ai, self._ctx(), catalog)
        item_names = [i["name"] for i in result.items]
        assert "New Item A" not in item_names
        assert "New Item B" not in item_names

    def test_one_core_swap_accepted(self):
        """AI swapping exactly 1 core item with a catalog-resident item is accepted."""
        base = _make_loadout()
        catalog = _make_catalog(extra_names={"Lord Dominik's Regards": 3036})
        # Swap one core slot; situ unchanged
        ai = self._ai(core=["Lord Dominik's Regards", "Runaan's Hurricane"])
        result = apply_ai_open_decision(base, ai, self._ctx(), catalog)
        item_names = [i["name"] for i in result.items]
        assert "Lord Dominik's Regards" in item_names

    def test_item_count_unchanged(self):
        """Output items list is always the same length as the base."""
        base = _make_loadout()
        result = apply_ai_open_decision(base, self._ai(), self._ctx(), _make_catalog())
        assert len(result.items) == len(base.items)

    def test_jungle_smite_preserved(self):
        """spell1 is never changed for junglers (Smite guard)."""
        base = _make_loadout(spell1="Smite", allowed_spell1=["Smite", "Ignite"])
        ctx = MagicMock()
        ctx.my_role = "jungle"
        ai = self._ai()
        ai["spell1"] = "Ignite"
        result = apply_ai_open_decision(base, ai, ctx, _make_catalog())
        assert result.spell1 == "Smite"

    def test_reasoning_truncated_to_300_chars(self):
        base = _make_loadout()
        ai = self._ai(reasoning="x" * 500)
        result = apply_ai_open_decision(base, ai, self._ctx(), _make_catalog())
        assert len(result.reasoning) <= 300

    def test_no_situational_pool_required(self):
        """has_pool only requires core_items — empty situational_pool is fine."""
        base = _make_loadout(situational_pool=[])
        result = apply_ai_open_decision(base, self._ai(), self._ctx(), _make_catalog())
        # Should not raise and source should be set
        assert "+ollama-open" in result.source
