"""Offline tests for champion-aware, pool-constrained rune selection.

Covers:
- _DEPRECATED_KEYSTONES not in KEYSTONES or KEYSTONE_STYLE
- CHAMPION_RUNE_ARCHETYPES structure and validity
- rune_pool_for_champion lookup
- _valid_rune_block with and without rune_pool
- compile_prompt rune section varies by champion
- apply_ai_decision / apply_ai_open_decision pool-constrained validation

No LCU, Ollama, or network required.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


from sylqon.ai.prompts import compile_prompt, rune_pool_for_champion
from sylqon.data import static
from sylqon.data.catalog import Catalog
from sylqon.loadout import (
    Loadout,
    _valid_rune_block,
    apply_ai_decision,
    apply_ai_open_decision,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_loadout(**overrides) -> Loadout:
    boots = {"id": 3006, "name": "Berserker's Greaves"}
    core = [
        {"id": 3031, "name": "Infinity Edge"},
        {"id": 3085, "name": "Runaan's Hurricane"},
    ]
    situ_pool = [
        {"id": 3094, "name": "Rapidfire Cannon", "description": "Boost attack range"},
        {"id": 3072, "name": "Bloodthirster", "description": "Lifesteal"},
    ]
    defaults = dict(
        items=[boots] + core + situ_pool,
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
        situational_pool=list(situ_pool),
    )
    defaults.update(overrides)
    return Loadout(**defaults)


def _make_catalog() -> MagicMock:
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
    catalog = MagicMock(spec=Catalog)
    catalog.item_id.side_effect = lambda n: name_to_id.get(n)
    return catalog


def _make_ctx(champion: str = "Jinx", role: str = "bottom") -> MagicMock:
    ctx = MagicMock()
    ctx.my_champion = champion
    ctx.my_role = role
    ctx.enemies = []
    ctx.allies = []
    ctx.team_threat_summary.return_value = {
        "heavy_healing": False, "tanks": 0, "suppression": False,
        "heavy_cc_count": 0, "burst_ad": False, "burst_ap": False,
        "physical_threats": 0, "magic_threats": 0,
    }
    return ctx


def _candidate() -> dict:
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
        "situational_pool": [
            {"id": 3094, "name": "Rapidfire Cannon", "description": "Range boost"},
            {"id": 3072, "name": "Bloodthirster", "description": "Lifesteal"},
        ],
        "keystone": "Lethal Tempo",
        "primary_runes": ["Legend: Alacrity", "Triumph", "Coup de Grace"],
        "secondary_style": "Domination",
        "secondary_runes": ["Taste of Blood", "Treasure Hunter"],
        "stat_shards": ["Adaptive Force", "Adaptive Force", "Health"],
        "spell1": "Heal",
        "spell2": "Flash",
        "spell_options": ["Heal", "Flash", "Exhaust"],
    }


# ---------------------------------------------------------------------------
# static.py — deprecated keystones
# ---------------------------------------------------------------------------

class TestDeprecatedKeystones:
    def test_deathfire_touch_removed(self):
        """Deathfire Touch left the game with Runes Reforged; keeping it in
        KEYSTONES let the AI pick it, and the LCU silently drops the unknown
        perk id — a broken injected page. It must stay out."""
        assert "Deathfire Touch" not in static.KEYSTONES
        assert "Deathfire Touch" not in static.KEYSTONE_STYLE

    def test_deathfire_touch_block_rejected(self):
        from sylqon.loadout import _valid_rune_block
        assert not _valid_rune_block(
            "Deathfire Touch",
            ["Manaflow Band", "Transcendence", "Scorch"],
            ["Taste of Blood", "Treasure Hunter"],
            "Domination",
        )

    def test_keystones_and_keystone_style_match(self):
        """Every entry in KEYSTONES must have a style mapping."""
        for ks in static.KEYSTONES:
            assert ks in static.KEYSTONE_STYLE, f"{ks} missing from KEYSTONE_STYLE"


# ---------------------------------------------------------------------------
# static.py — CHAMPION_RUNE_ARCHETYPES integrity
# ---------------------------------------------------------------------------

class TestChampionRuneArchetypes:
    def test_known_champions_present(self):
        for champ in ("Jinx", "Zed", "Darius", "Thresh", "Soraka"):
            assert champ in static.CHAMPION_RUNE_ARCHETYPES

    def test_all_keystone_options_in_keystones(self):
        for champ, archetype in static.CHAMPION_RUNE_ARCHETYPES.items():
            for ks in archetype["keystone_options"]:
                assert ks in static.KEYSTONES, (
                    f"{champ}: keystone '{ks}' not in KEYSTONES"
                )

    def test_all_primary_minor_flex_names_in_minor_runes(self):
        for champ, archetype in static.CHAMPION_RUNE_ARCHETYPES.items():
            for rune in archetype["primary_minor_flex"]:
                assert rune in static.MINOR_RUNES, (
                    f"{champ}: primary minor '{rune}' not in MINOR_RUNES"
                )

    def test_all_secondary_style_options_in_rune_styles(self):
        for champ, archetype in static.CHAMPION_RUNE_ARCHETYPES.items():
            for style in archetype["secondary_style_options"]:
                assert style in static.RUNE_STYLES, (
                    f"{champ}: secondary style '{style}' not in RUNE_STYLES"
                )

    def test_all_secondary_minor_options_in_minor_runes(self):
        for champ, archetype in static.CHAMPION_RUNE_ARCHETYPES.items():
            for rune in archetype["secondary_minor_options"]:
                assert rune in static.MINOR_RUNES, (
                    f"{champ}: secondary minor '{rune}' not in MINOR_RUNES"
                )

    def test_keystone_options_not_empty(self):
        for champ, archetype in static.CHAMPION_RUNE_ARCHETYPES.items():
            assert len(archetype["keystone_options"]) >= 1, (
                f"{champ}: keystone_options must not be empty"
            )

    def test_secondary_minor_options_not_all_from_primary_style(self):
        """Secondary minor pool should not all belong to the primary keystone tree."""
        for champ, archetype in static.CHAMPION_RUNE_ARCHETYPES.items():
            primary_ks = archetype["keystone_options"][0]
            primary_style = static.KEYSTONE_STYLE[primary_ks]
            secondary_styles = archetype["secondary_style_options"]
            # At least one secondary style must differ from the primary style
            assert any(s != primary_style for s in secondary_styles), (
                f"{champ}: all secondary styles match primary style {primary_style}"
            )

    def test_all_keystone_options_in_keystones_includes_deathfire_if_present(self):
        """If an archetype lists Deathfire Touch it must be in KEYSTONES (it is)."""
        for champ, archetype in static.CHAMPION_RUNE_ARCHETYPES.items():
            for ks in archetype["keystone_options"]:
                assert ks in static.KEYSTONES, (
                    f"{champ}: keystone '{ks}' not in KEYSTONES"
                )


# ---------------------------------------------------------------------------
# rune_pool_for_champion
# ---------------------------------------------------------------------------

class TestRunePoolForChampion:
    def test_known_champion_returns_dict(self):
        pool = rune_pool_for_champion("Jinx")
        assert isinstance(pool, dict)

    def test_known_champion_has_required_keys(self):
        pool = rune_pool_for_champion("Jinx")
        assert pool is not None
        for key in ("keystone_options", "primary_minor_flex",
                    "secondary_style_options", "secondary_minor_options"):
            assert key in pool

    def test_unknown_champion_returns_none(self):
        assert rune_pool_for_champion("NonexistentChampXYZ") is None

    def test_fallback_champion_returns_none(self):
        # A champion not in the dict (e.g. Tristana) should return None
        assert rune_pool_for_champion("Tristana") is None

    def test_case_sensitive(self):
        # "jinx" != "Jinx"
        assert rune_pool_for_champion("jinx") is None


# ---------------------------------------------------------------------------
# _valid_rune_block — global validation (no pool)
# ---------------------------------------------------------------------------

class TestValidRuneBlockGlobal:
    def test_valid_precision_block(self):
        assert _valid_rune_block(
            "Lethal Tempo",
            ["Legend: Alacrity", "Triumph", "Coup de Grace"],
            ["Taste of Blood", "Treasure Hunter"],
            "Domination",
        )

    def test_invalid_keystone_rejected(self):
        assert not _valid_rune_block(
            "Deathfire Touch",
            ["Legend: Alacrity", "Triumph", "Coup de Grace"],
            ["Taste of Blood", "Treasure Hunter"],
            "Domination",
        )

    def test_wrong_primary_tree_rejected(self):
        # Primary runes don't match Lethal Tempo's Precision tree
        assert not _valid_rune_block(
            "Lethal Tempo",
            ["Taste of Blood", "Eyeball Collection", "Treasure Hunter"],
            ["Taste of Blood", "Treasure Hunter"],
            "Domination",
        )

    def test_secondary_same_as_primary_rejected(self):
        assert not _valid_rune_block(
            "Lethal Tempo",
            ["Legend: Alacrity", "Triumph", "Coup de Grace"],
            ["Coup de Grace", "Cut Down"],
            "Precision",
        )

    def test_wrong_secondary_tree_runes_rejected(self):
        # Secondary runes don't match the secondary_style
        assert not _valid_rune_block(
            "Lethal Tempo",
            ["Legend: Alacrity", "Triumph", "Coup de Grace"],
            ["Manaflow Band", "Gathering Storm"],  # Sorcery, not Domination
            "Domination",
        )

    def test_wrong_primary_count_rejected(self):
        assert not _valid_rune_block(
            "Lethal Tempo",
            ["Legend: Alacrity", "Triumph"],
            ["Taste of Blood", "Treasure Hunter"],
            "Domination",
        )

    def test_wrong_secondary_count_rejected(self):
        assert not _valid_rune_block(
            "Lethal Tempo",
            ["Legend: Alacrity", "Triumph", "Coup de Grace"],
            ["Taste of Blood"],
            "Domination",
        )


# ---------------------------------------------------------------------------
# _valid_rune_block — pool-constrained validation
# ---------------------------------------------------------------------------

class TestValidRuneBlockWithPool:
    def _jinx_pool(self) -> dict:
        return rune_pool_for_champion("Jinx")

    def test_valid_block_within_pool_accepted(self):
        pool = self._jinx_pool()
        # Lethal Tempo is Jinx's meta default; Domination is a valid secondary
        assert _valid_rune_block(
            "Lethal Tempo",
            ["Triumph", "Legend: Alacrity", "Coup de Grace"],
            ["Taste of Blood", "Treasure Hunter"],
            "Domination",
            rune_pool=pool,
        )

    def test_keystone_not_in_pool_rejected(self):
        pool = self._jinx_pool()
        # Electrocute is not in Jinx's keystone_options
        assert not _valid_rune_block(
            "Electrocute",
            ["Cheap Shot", "Eyeball Collection", "Treasure Hunter"],
            ["Manaflow Band", "Gathering Storm"],
            "Sorcery",
            rune_pool=pool,
        )

    def test_secondary_style_not_in_pool_rejected(self):
        pool = self._jinx_pool()
        # Inspiration is not in Jinx's secondary_style_options
        assert not _valid_rune_block(
            "Lethal Tempo",
            ["Triumph", "Legend: Alacrity", "Coup de Grace"],
            ["Magical Footwear", "Biscuit Delivery"],
            "Inspiration",
            rune_pool=pool,
        )

    def test_secondary_rune_not_in_pool_rejected(self):
        pool = self._jinx_pool()
        # "Relentless Hunter" not in Jinx's secondary_minor_options
        assert not _valid_rune_block(
            "Lethal Tempo",
            ["Triumph", "Legend: Alacrity", "Coup de Grace"],
            ["Relentless Hunter", "Treasure Hunter"],
            "Domination",
            rune_pool=pool,
        )

    def test_none_pool_skips_pool_checks(self):
        # Without pool, any valid global block passes
        assert _valid_rune_block(
            "Electrocute",
            ["Cheap Shot", "Eyeball Collection", "Treasure Hunter"],
            ["Manaflow Band", "Gathering Storm"],
            "Sorcery",
            rune_pool=None,
        )

    def test_zed_electrocute_accepted(self):
        pool = rune_pool_for_champion("Zed")
        assert pool is not None
        assert _valid_rune_block(
            "Electrocute",
            ["Cheap Shot", "Eyeball Collection", "Treasure Hunter"],
            ["Triumph", "Coup de Grace"],
            "Precision",
            rune_pool=pool,
        )

    def test_zed_wrong_secondary_style_rejected(self):
        pool = rune_pool_for_champion("Zed")
        assert pool is not None
        # Resolve is not in Zed's secondary_style_options
        assert not _valid_rune_block(
            "Electrocute",
            ["Cheap Shot", "Eyeball Collection", "Treasure Hunter"],
            ["Bone Plating", "Second Wind"],
            "Resolve",
            rune_pool=pool,
        )


# ---------------------------------------------------------------------------
# compile_prompt — rune section varies by champion
# ---------------------------------------------------------------------------

class TestCompilePromptRuneSection:
    def test_known_champion_uses_curated_section(self):
        ctx = _make_ctx(champion="Jinx")
        prompt = compile_prompt(ctx, _candidate(), _make_catalog())
        assert "curated for Jinx" in prompt
        assert "Lethal Tempo" in prompt

    def test_unknown_champion_uses_global_section(self):
        ctx = _make_ctx(champion="Tristana")
        prompt = compile_prompt(ctx, _candidate(), _make_catalog())
        assert "RUNE POOL: keystones" in prompt
        # Global section lists the raw keystones dict — Fleet Footwork will be there
        assert "Fleet Footwork" in prompt

    def test_known_champion_schema_hints_are_pool_specific(self):
        ctx = _make_ctx(champion="Jinx")
        prompt = compile_prompt(ctx, _candidate(), _make_catalog())
        # The response_schema JSON section should mention the curated pool lists
        # We check the presence of a known pool item in a response schema hint
        schema_section = prompt[prompt.rfind("{"):]
        assert "Lethal Tempo" in schema_section or "Fleet Footwork" in schema_section

    def test_unknown_champion_schema_hints_are_generic(self):
        ctx = _make_ctx(champion="Tristana")
        prompt = compile_prompt(ctx, _candidate(), _make_catalog())
        schema_section = prompt[prompt.rfind("{"):]
        assert "exact keystone name" in schema_section


# ---------------------------------------------------------------------------
# apply_ai_decision — pool-constrained rune validation
# ---------------------------------------------------------------------------

class TestApplyAiDecisionRunePool:
    def _ctx(self, champion: str = "Jinx", role: str = "bottom") -> MagicMock:
        ctx = MagicMock()
        ctx.my_champion = champion
        ctx.my_role = role
        ctx.team_threat_summary.return_value = {
            "heavy_healing": False, "tanks": 0, "suppression": False,
            "heavy_cc_count": 0, "burst_ad": False, "burst_ap": False,
            "physical_threats": 0, "magic_threats": 0,
        }
        return ctx

    def _ai_valid_jinx(self) -> dict:
        return {
            "core_items": ["Infinity Edge", "Runaan's Hurricane"],
            "situational_items": ["Rapidfire Cannon", "Bloodthirster"],
            "keystone": "Lethal Tempo",
            "primary_runes": ["Triumph", "Legend: Alacrity", "Coup de Grace"],
            "secondary_style": "Domination",
            "secondary_runes": ["Taste of Blood", "Treasure Hunter"],
            "stat_shards": ["Adaptive Force", "Adaptive Force", "Health"],
            "spell1": "Heal",
            "spell2": "Flash",
            "reasoning": "Standard Jinx build.",
        }

    def test_valid_pool_rune_block_accepted(self):
        base = _make_loadout()
        ai = self._ai_valid_jinx()
        result = apply_ai_decision(base, ai, self._ctx("Jinx"), _make_catalog())
        assert result.rune_perk_ids[0] == static.KEYSTONES["Lethal Tempo"]

    def test_keystone_outside_jinx_pool_rejected(self):
        base = _make_loadout()
        ai = self._ai_valid_jinx()
        # Electrocute is not in Jinx's pool — rune block should be rejected
        ai["keystone"] = "Electrocute"
        ai["primary_runes"] = ["Cheap Shot", "Eyeball Collection", "Treasure Hunter"]
        ai["secondary_style"] = "Sorcery"
        ai["secondary_runes"] = ["Manaflow Band", "Gathering Storm"]
        result = apply_ai_decision(base, ai, self._ctx("Jinx"), _make_catalog())
        # Should keep base rune perk ids unchanged
        assert result.rune_perk_ids == base.rune_perk_ids

    def test_secondary_style_outside_jinx_pool_rejected(self):
        base = _make_loadout()
        ai = self._ai_valid_jinx()
        # Inspiration not in Jinx's secondary_style_options
        ai["secondary_style"] = "Inspiration"
        ai["secondary_runes"] = ["Magical Footwear", "Biscuit Delivery"]
        result = apply_ai_decision(base, ai, self._ctx("Jinx"), _make_catalog())
        assert result.rune_perk_ids == base.rune_perk_ids

    def test_unknown_champion_accepts_any_valid_global_block(self):
        """For a champion not in CHAMPION_RUNE_ARCHETYPES, pool constraints are skipped."""
        base = _make_loadout()
        ai = self._ai_valid_jinx()
        # Use Electrocute (not in Jinx's pool), but Tristana has no pool — should pass global check
        ai["keystone"] = "Electrocute"
        ai["primary_runes"] = ["Cheap Shot", "Eyeball Collection", "Treasure Hunter"]
        ai["secondary_style"] = "Sorcery"
        ai["secondary_runes"] = ["Manaflow Band", "Gathering Storm"]
        result = apply_ai_decision(base, ai, self._ctx("Tristana"), _make_catalog())
        assert result.rune_perk_ids[0] == static.KEYSTONES["Electrocute"]

    def test_source_suffix_set_when_rune_accepted(self):
        base = _make_loadout()
        ai = self._ai_valid_jinx()
        result = apply_ai_decision(base, ai, self._ctx("Jinx"), _make_catalog())
        assert "+ollama" in result.source


# ---------------------------------------------------------------------------
# apply_ai_open_decision — pool-constrained rune validation
# ---------------------------------------------------------------------------

class TestApplyAiOpenDecisionRunePool:
    def _ctx(self, champion: str = "Jinx") -> MagicMock:
        ctx = MagicMock()
        ctx.my_champion = champion
        ctx.my_role = "bottom"
        return ctx

    def _ai(self) -> dict:
        return {
            "core_items": ["Infinity Edge", "Runaan's Hurricane"],
            "situational_items": ["Rapidfire Cannon", "Bloodthirster"],
            "keystone": "Lethal Tempo",
            "primary_runes": ["Triumph", "Legend: Alacrity", "Coup de Grace"],
            "secondary_style": "Domination",
            "secondary_runes": ["Taste of Blood", "Treasure Hunter"],
            "stat_shards": ["Adaptive Force", "Adaptive Force", "Health"],
            "spell1": "Heal",
            "spell2": "Flash",
            "reasoning": "Standard.",
        }

    def test_valid_pool_block_accepted_in_open_mode(self):
        base = _make_loadout()
        result = apply_ai_open_decision(base, self._ai(), self._ctx("Jinx"), _make_catalog())
        assert result.rune_perk_ids[0] == static.KEYSTONES["Lethal Tempo"]

    def test_invalid_pool_block_rejected_in_open_mode(self):
        base = _make_loadout()
        ai = self._ai()
        ai["keystone"] = "Electrocute"
        ai["primary_runes"] = ["Cheap Shot", "Eyeball Collection", "Treasure Hunter"]
        ai["secondary_style"] = "Sorcery"
        ai["secondary_runes"] = ["Manaflow Band", "Gathering Storm"]
        result = apply_ai_open_decision(base, ai, self._ctx("Jinx"), _make_catalog())
        assert result.rune_perk_ids == base.rune_perk_ids

    def test_no_pool_champion_open_mode_global_check_only(self):
        base = _make_loadout()
        ai = self._ai()
        ai["keystone"] = "Electrocute"
        ai["primary_runes"] = ["Cheap Shot", "Eyeball Collection", "Treasure Hunter"]
        ai["secondary_style"] = "Sorcery"
        ai["secondary_runes"] = ["Manaflow Band", "Gathering Storm"]
        result = apply_ai_open_decision(base, ai, self._ctx("Tristana"), _make_catalog())
        assert result.rune_perk_ids[0] == static.KEYSTONES["Electrocute"]
