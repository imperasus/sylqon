"""Offline tests for the code-level loadout guarantees added on top of the AI
filter:

- ``_enforce_counter_items`` — threat-mandated counter items always present;
- threat-aware ``_apply_shards`` — defense/flex shards adapt to AD/AP/CC;
- meta-core ``_apply_runes`` — keystone/primary kept unless a strong threat
  justifies a pool-legal swap;
- the seed-derived ``rune_pool`` module (build → pool, merge, register).

All synthetic: no LCU, Ollama, or network.

Run: python -m pytest tests/test_counter_enforcement.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon import loadout as loadout_mod
from sylqon.data import rune_pool, static
from sylqon.lcu.lobby import EnemyProfile, MatchContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _StubCatalog:
    """Minimal catalog; counter enforcement reads ids off pool items, so this is
    only a fallback resolver and is barely exercised."""

    def item_id(self, name):  # pragma: no cover - pool items already carry ids
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


# A top build (6 items: boots + 3 core + 2 situational) whose core and default
# situational picks carry NO counter tags, so any mandated tag must be pulled
# from the pool. The pool offers one item for every counter category.
def _build(role="top"):
    boots = {"id": 3006, "name": "Berserker's Greaves"}           # no counter tag
    core = [{"id": 3031, "name": "Infinity Edge"},                # no tag
            {"id": 3072, "name": "Bloodthirster"},                # no tag
            {"id": 6672, "name": "Kraken Slayer"}]                # no tag
    default_situ = [{"id": 3078, "name": "Trinity Force"},        # no tag
                    {"id": 3508, "name": "Essence Reaver"}]       # no tag
    pool = [
        {"id": 3033, "name": "Mortal Reminder", "description": "anti-heal"},
        {"id": 3036, "name": "Lord Dominik's Regards", "description": "%pen"},
        {"id": 3140, "name": "Quicksilver Sash", "description": "anti-cc"},
        {"id": 3026, "name": "Guardian Angel", "description": "survival"},
        {"id": 3143, "name": "Randuin's Omen", "description": "armor"},
        {"id": 3065, "name": "Spirit Visage", "description": "mr"},
    ]
    return {
        "boots": boots, "boots_pool": [boots],
        "core_items": core, "situational_pool": pool,
        "items": [boots] + core + default_situ,
        "starting_items": [],
        "keystone": "Conqueror",
        "primary_runes": ["Triumph", "Legend: Alacrity", "Last Stand"],
        "secondary_style": "Resolve", "secondary_runes": ["Second Wind", "Overgrowth"],
        "stat_shards": ["Adaptive Force", "Adaptive Force", "Health"],
        "spell1": "Ghost", "spell2": "Flash",
    }


def _final(enemies, role="top"):
    """Compile the candidate then apply with NO AI — exercising pure code-level
    enforcement on the deterministic base build."""
    ctx = _ctx(enemies, role=role)
    build = _build(role)
    base = loadout_mod.from_candidate(build, ctx, "seed")
    out = loadout_mod.apply_ai_decision(base, None, ctx, _StubCatalog(), build)
    return out, build


def _has_tag(items, tag):
    return any(tag in static.ITEM_COUNTER_TAGS.get(i.get("id", 0), ())
              for i in items)


# ---------------------------------------------------------------------------
# Counter-item enforcement
# ---------------------------------------------------------------------------

class TestCounterItemEnforcement:
    def test_heavy_healing_forces_anti_heal(self):
        out, _ = _final([_enemy("Soraka", threats=["heavy_healing"])])
        assert _has_tag(out.items, "anti_heal")
        assert "Mortal Reminder" in [i["name"] for i in out.items]

    def test_two_tanks_force_percent_pen(self):
        enemies = [_enemy("Ornn", damage_type="AD", threats=["tank"]),
                   _enemy("Sion", damage_type="AD", threats=["tank"])]
        out, _ = _final(enemies)
        assert _has_tag(out.items, "percent_pen") or _has_tag(out.items, "tank_shred")

    def test_suppression_forces_qss_specifically(self):
        # Only QSS/Mercurial answer suppression — tenacity items don't count.
        out, _ = _final([_enemy("Malzahar", threats=["suppression"])])
        assert _has_tag(out.items, "anti_suppression")
        assert "Quicksilver Sash" in [i["name"] for i in out.items]

    def test_burst_forces_survival_item(self):
        out, _ = _final([_enemy("Zed", damage_type="AD", threats=["burst_ad"])])
        assert _has_tag(out.items, "anti_burst")

    def test_no_threat_leaves_build_unchanged(self):
        out, build = _final([_enemy("Lux", threats=[])])
        assert [i["id"] for i in out.items] == [i["id"] for i in build["items"]]

    def test_item_count_and_boots_core_preserved(self):
        out, build = _final([_enemy("Soraka", threats=["heavy_healing"])])
        assert len(out.items) == len(build["items"])
        # boots slot + 3 core slots are never disturbed
        assert [i["id"] for i in out.items[:4]] == \
               [i["id"] for i in build["items"][:4]]

    def test_already_covered_is_not_duplicated(self):
        # Pool item already chosen as a default situational → no extra swap.
        build = _build()
        build["items"][-1] = {"id": 3033, "name": "Mortal Reminder"}  # anti-heal present
        ctx = _ctx([_enemy("Soraka", threats=["heavy_healing"])])
        base = loadout_mod.from_candidate(build, ctx, "seed")
        out = loadout_mod.apply_ai_decision(base, None, ctx, _StubCatalog(), build)
        assert sum(1 for i in out.items if i["id"] == 3033) == 1

    def test_deterministic(self):
        a, _ = _final([_enemy("Soraka", threats=["heavy_healing"]),
                       _enemy("Zed", damage_type="AD", threats=["burst_ad"])])
        b, _ = _final([_enemy("Soraka", threats=["heavy_healing"]),
                       _enemy("Zed", damage_type="AD", threats=["burst_ad"])])
        assert [i["id"] for i in a.items] == [i["id"] for i in b.items]


# ---------------------------------------------------------------------------
# Threat-aware stat shards
# ---------------------------------------------------------------------------

class TestThreatAwareShards:
    def _shards(self, threat: dict, base=None):
        base = base or ["Adaptive Force", "Adaptive Force", "Health"]
        return loadout_mod._compute_default_shards(threat, base)

    def test_ap_heavy_defense_health_scaling(self):
        out = self._shards({"magic_threats": 4, "physical_threats": 1})
        assert out[1] == "Health Scaling"   # flex bumped vs decisive AP
        assert out[2] == "Health Scaling"   # defense

    def test_heavy_cc_defense_tenacity(self):
        out = self._shards({"heavy_cc_count": 3})
        assert out[2] == "Tenacity and Slow Resist"

    def test_suppression_alone_keeps_base_defense(self):
        # Tenacity has no effect on suppression duration — a lone suppressor
        # must NOT flip the defense shard (the QSS item mandate answers it).
        out = self._shards({"suppression": True})
        assert out[2] == "Health"

    def test_ad_heavy_defense_health(self):
        out = self._shards({"physical_threats": 5, "magic_threats": 0})
        assert out[2] == "Health"

    def test_ad_burst_defense_tenacity(self):
        out = self._shards({"physical_threats": 5, "magic_threats": 0, "burst_ad": True})
        assert out[2] == "Tenacity and Slow Resist"

    def test_balanced_keeps_base_defense(self):
        out = self._shards({"physical_threats": 2, "magic_threats": 2},
                           base=["Attack Speed", "Move Speed", "Health"])
        assert out == ["Attack Speed", "Move Speed", "Health"]

    def test_default_shards_written_without_ai(self):
        out, _ = _final([_enemy("Syndra", damage_type="AP"),
                         _enemy("Lux", damage_type="AP"),
                         _enemy("Brand", damage_type="AP")])
        # 3 AP → defense shard becomes Health Scaling even with no AI shard output.
        assert out.shard_ids[2] == static.STAT_SHARDS["Health Scaling"]

    def test_ai_defense_gate_rejects_greedy_pick(self):
        # Heavy CC comp; AI tries a non-tenacity defense → computed Tenacity wins.
        ctx = _ctx([_enemy(n, threats=["heavy_cc"]) for n in ("Leona", "Lux", "Sejuani")])
        build = _build()
        base = loadout_mod.from_candidate(build, ctx, "seed")
        ai = {
            "stat_shards": ["Adaptive Force", "Adaptive Force", "Health"],
        }
        out = loadout_mod.apply_ai_decision(base, ai, ctx, _StubCatalog(), build)
        assert out.shard_ids[2] == static.STAT_SHARDS["Tenacity and Slow Resist"]

    def test_ai_defense_gate_accepts_consistent_pick(self):
        ctx = _ctx([_enemy(n, threats=["heavy_cc"]) for n in ("Leona", "Lux", "Sejuani")])
        build = _build()
        base = loadout_mod.from_candidate(build, ctx, "seed")
        ai = {"stat_shards": ["Adaptive Force", "Adaptive Force",
                              "Tenacity and Slow Resist"]}
        out = loadout_mod.apply_ai_decision(base, ai, ctx, _StubCatalog(), build)
        assert out.shard_ids[2] == static.STAT_SHARDS["Tenacity and Slow Resist"]

    def test_ai_offense_flex_clamped_to_meta_or_adaptive(self):
        # Within-row but champion-alien offense/flex picks (e.g. Attack Speed
        # when the meta page runs Adaptive) never override the op.gg shards.
        ctx = _ctx([_enemy("Garen", damage_type="AD")])
        build = _build()  # base shards: Adaptive / Adaptive / Health
        base = loadout_mod.from_candidate(build, ctx, "seed")
        ai = {"stat_shards": ["Attack Speed", "Move Speed", "Health"]}
        out = loadout_mod.apply_ai_decision(base, ai, ctx, _StubCatalog(), build)
        assert out.shard_ids[0] == static.STAT_SHARDS["Adaptive Force"]
        assert out.shard_ids[1] == static.STAT_SHARDS["Adaptive Force"]

    def test_ai_offense_matching_meta_page_kept(self):
        ctx = _ctx([_enemy("Garen", damage_type="AD")])
        build = _build()
        build["stat_shards"] = ["Attack Speed", "Adaptive Force", "Health"]
        base = loadout_mod.from_candidate(build, ctx, "seed")
        ai = {"stat_shards": ["Attack Speed", "Adaptive Force", "Health"]}
        out = loadout_mod.apply_ai_decision(base, ai, ctx, _StubCatalog(), build)
        assert out.shard_ids[0] == static.STAT_SHARDS["Attack Speed"]


# ---------------------------------------------------------------------------
# Meta-core rune preference
# ---------------------------------------------------------------------------

def _jinx_build():
    boots = {"id": 3006, "name": "Berserker's Greaves"}
    core = [{"id": 6672, "name": "Kraken Slayer"},
            {"id": 3031, "name": "Infinity Edge"},
            {"id": 3046, "name": "Phantom Dancer"}]
    pool = [{"id": 3072, "name": "Bloodthirster"},
            {"id": 3026, "name": "Guardian Angel"}]
    return {
        "boots": boots, "boots_pool": [boots], "core_items": core,
        "situational_pool": pool, "items": [boots] + core + pool,
        "starting_items": [],
        "keystone": "Lethal Tempo",
        "primary_runes": ["Triumph", "Legend: Alacrity", "Coup de Grace"],
        "secondary_style": "Domination",
        "secondary_runes": ["Taste of Blood", "Treasure Hunter"],
        "stat_shards": ["Attack Speed", "Adaptive Force", "Health"],
        "spell1": "Heal", "spell2": "Flash",
    }


def _ai_runes(keystone="Fleet Footwork",
              primary=("Triumph", "Legend: Alacrity", "Coup de Grace")):
    return {
        "keystone": keystone,
        "primary_runes": list(primary),
        "secondary_style": "Domination",
        "secondary_runes": ["Taste of Blood", "Treasure Hunter"],
        "reasoning": "rune test",
    }


class TestMetaCoreRunes:
    def test_keystone_swap_rejected_without_strong_threat(self):
        build = _jinx_build()
        ctx = _ctx([_enemy("Garen", damage_type="AD")], role="bottom", champion="Jinx")
        base = loadout_mod.from_candidate(build, ctx, "opgg")
        out = loadout_mod.apply_ai_decision(base, _ai_runes("Fleet Footwork"),
                                            ctx, _StubCatalog(), build)
        # Fleet Footwork is in Jinx's pool but no strong threat → keep meta keystone.
        assert out.rune_perk_ids[0] == static.KEYSTONES["Lethal Tempo"]

    def test_keystone_swap_accepted_under_strong_threat(self):
        build = _jinx_build()
        ctx = _ctx([_enemy("Syndra", damage_type="AP", threats=["burst_ap"])],
                   role="bottom", champion="Jinx")
        base = loadout_mod.from_candidate(build, ctx, "opgg")
        out = loadout_mod.apply_ai_decision(base, _ai_runes("Fleet Footwork"),
                                            ctx, _StubCatalog(), build)
        assert out.rune_perk_ids[0] == static.KEYSTONES["Fleet Footwork"]

    def test_primary_rune_outside_flex_rejected(self):
        build = _jinx_build()
        ctx = _ctx([_enemy("Garen", damage_type="AD")], role="bottom", champion="Jinx")
        base = loadout_mod.from_candidate(build, ctx, "opgg")
        # Same (meta) keystone but a primary rune NOT in Jinx's flex pool.
        ai = _ai_runes("Lethal Tempo",
                       primary=("Triumph", "Legend: Haste", "Coup de Grace"))
        out = loadout_mod.apply_ai_decision(base, ai, ctx, _StubCatalog(), build)
        assert out.rune_perk_ids == base.rune_perk_ids

    def test_no_pool_champion_keeps_permissive_behaviour(self):
        build = _jinx_build()
        ctx = _ctx([_enemy("Garen", damage_type="AD")], role="bottom",
                   champion="ChampWithNoPoolXYZ")
        base = loadout_mod.from_candidate(build, ctx, "opgg")
        # No champion pool → any globally valid block (incl. keystone swap) is kept.
        ai = {
            "keystone": "Press the Attack",
            "primary_runes": ["Triumph", "Legend: Alacrity", "Coup de Grace"],
            "secondary_style": "Domination",
            "secondary_runes": ["Taste of Blood", "Treasure Hunter"],
        }
        out = loadout_mod.apply_ai_decision(base, ai, ctx, _StubCatalog(), build)
        assert out.rune_perk_ids[0] == static.KEYSTONES["Press the Attack"]


# ---------------------------------------------------------------------------
# Seed-derived rune_pool module
# ---------------------------------------------------------------------------

class TestRunePoolModule:
    def test_seed_only_champion_has_pool(self):
        # Kog'Maw has a seed build but no static archetype.
        assert "Kog'Maw" not in static.CHAMPION_RUNE_ARCHETYPES
        pool = rune_pool.rune_pool_for_champion("Kog'Maw")
        assert pool is not None
        for key in ("keystone_options", "primary_minor_flex",
                    "secondary_style_options", "secondary_minor_options"):
            assert pool[key]

    def test_static_and_seed_merged_for_known_champion(self):
        pool = rune_pool.rune_pool_for_champion("Jinx")
        assert pool is not None
        # Static meta default stays first.
        assert pool["keystone_options"][0] == "Lethal Tempo"
        # Seed Jinx runs an Inspiration secondary → merged in on top of static.
        assert "Inspiration" in pool["secondary_style_options"]

    def test_unknown_champion_is_none(self):
        assert rune_pool.rune_pool_for_champion("DefinitelyNotAChampion") is None

    def test_pool_is_self_consistent(self):
        for champ in ("Jinx", "Kog'Maw", "Zed"):
            pool = rune_pool.rune_pool_for_champion(champ)
            default = pool["keystone_options"][0]
            primary_style = static.KEYSTONE_STYLE[default]
            assert any(s != primary_style for s in pool["secondary_style_options"])

    def test_register_build_widens_runtime_pool(self):
        champ = "ZiggsRunePoolTest"
        assert rune_pool.rune_pool_for_champion(champ) is None
        try:
            rune_pool.register_build(champ, {
                "keystone": "Arcane Comet",
                "primary_runes": ["Manaflow Band", "Transcendence", "Scorch"],
                "secondary_style": "Inspiration",
                "secondary_runes": ["Magical Footwear", "Biscuit Delivery"],
            })
            pool = rune_pool.rune_pool_for_champion(champ)
            assert pool is not None
            assert pool["keystone_options"] == ["Arcane Comet"]
            assert "Inspiration" in pool["secondary_style_options"]
        finally:
            rune_pool._RUNTIME_INDEX.pop(champ, None)

    def test_register_build_ignores_garbage(self):
        champ = "GarbageRuneChampTest"
        rune_pool.register_build(champ, {"keystone": "Not A Real Keystone"})
        assert rune_pool.rune_pool_for_champion(champ) is None


# ---------------------------------------------------------------------------
# Champion damage-type aware counter eligibility
# ---------------------------------------------------------------------------

# A build whose pool offers BOTH an AD and an AP option for anti-heal and %pen,
# so enforcement must pick the one matching the champion's damage class.
def _dual_build():
    boots = {"id": 3006, "name": "Berserker's Greaves"}
    core = [{"id": 3078, "name": "Trinity Force"},
            {"id": 3508, "name": "Essence Reaver"},
            {"id": 6672, "name": "Kraken Slayer"}]
    default_situ = [{"id": 3072, "name": "Bloodthirster"},
                    {"id": 3046, "name": "Phantom Dancer"}]
    pool = [
        {"id": 3033, "name": "Mortal Reminder"},        # anti_heal — ad_only
        {"id": 3165, "name": "Morellonomicon"},         # anti_heal — ap_only
        {"id": 3036, "name": "Lord Dominik's Regards"},  # percent_pen — ad_only
        {"id": 3135, "name": "Void Staff"},             # percent_pen — ap_only
        {"id": 3026, "name": "Guardian Angel"},         # anti_burst — universal
    ]
    return {
        "boots": boots, "boots_pool": [boots],
        "core_items": core, "situational_pool": pool,
        "items": [boots] + core + default_situ,
        "starting_items": [],
        "keystone": "Conqueror",
        "primary_runes": ["Triumph", "Legend: Alacrity", "Last Stand"],
        "secondary_style": "Resolve", "secondary_runes": ["Second Wind", "Overgrowth"],
        "stat_shards": ["Adaptive Force", "Adaptive Force", "Health"],
        "spell1": "Ghost", "spell2": "Flash",
    }


def _enforce_for(champion, enemies, role="middle"):
    ctx = _ctx(enemies, role=role, champion=champion)
    build = _dual_build()
    base = loadout_mod.from_candidate(build, ctx, "seed")
    out = loadout_mod.apply_ai_decision(base, None, ctx, _StubCatalog(), build)
    return [i["name"] for i in out.items]


class TestItemEligibilityHelper:
    def test_ad_champion_accepts_ad_only(self):
        assert loadout_mod._item_eligible_for_champion("Lord Dominik's Regards", "Garen")

    def test_ad_champion_rejects_ap_only(self):
        assert not loadout_mod._item_eligible_for_champion("Void Staff", "Garen")

    def test_ap_champion_accepts_ap_only(self):
        assert loadout_mod._item_eligible_for_champion("Void Staff", "Syndra")

    def test_ap_champion_rejects_ad_only(self):
        assert not loadout_mod._item_eligible_for_champion("Lord Dominik's Regards", "Syndra")

    def test_universal_item_always_eligible(self):
        for champ in ("Garen", "Syndra", "Jax", "UnknownChampXYZ"):
            assert loadout_mod._item_eligible_for_champion("Guardian Angel", champ)

    def test_mixed_champion_accepts_both(self):
        assert loadout_mod._item_eligible_for_champion("Void Staff", "Jax")
        assert loadout_mod._item_eligible_for_champion("Lord Dominik's Regards", "Jax")

    def test_unknown_champion_is_permissive(self):
        assert loadout_mod._item_eligible_for_champion("Void Staff", "NobodyChamp")
        assert loadout_mod._item_eligible_for_champion("Lord Dominik's Regards", "NobodyChamp")

    def test_unknown_item_is_universal(self):
        assert loadout_mod._item_eligible_for_champion("Totally Fake Item", "Syndra")


class TestDamageTypeAwareEnforcement:
    def test_ad_champion_gets_ad_anti_heal(self):
        names = _enforce_for("Garen", [_enemy("Soraka", threats=["heavy_healing"])])
        assert "Mortal Reminder" in names      # AD anti-heal
        assert "Morellonomicon" not in names   # AP anti-heal filtered out

    def test_ap_champion_gets_ap_anti_heal(self):
        names = _enforce_for("Syndra", [_enemy("Soraka", threats=["heavy_healing"])])
        assert "Morellonomicon" in names       # AP anti-heal
        assert "Mortal Reminder" not in names  # AD anti-heal filtered out

    def test_ad_champion_gets_ad_percent_pen(self):
        enemies = [_enemy("Ornn", damage_type="AD", threats=["tank"]),
                   _enemy("Sion", damage_type="AD", threats=["tank"])]
        names = _enforce_for("Garen", enemies)
        # An AD %pen item (LDR or Mortal Reminder, both carry percent_pen) lands;
        # the AP option never does.
        assert any(n in names for n in ("Lord Dominik's Regards", "Mortal Reminder"))
        assert "Void Staff" not in names

    def test_ap_champion_gets_ap_percent_pen(self):
        enemies = [_enemy("Ornn", damage_type="AD", threats=["tank"]),
                   _enemy("Sion", damage_type="AD", threats=["tank"])]
        names = _enforce_for("Syndra", enemies)
        assert "Void Staff" in names
        assert "Lord Dominik's Regards" not in names

    def test_mixed_champion_can_take_either(self):
        # A "mixed" champion isn't restricted — the first eligible pool item wins.
        names = _enforce_for("Jax", [_enemy("Soraka", threats=["heavy_healing"])])
        assert ("Mortal Reminder" in names) or ("Morellonomicon" in names)

    def test_universal_survival_item_used_regardless_of_type(self):
        for champ in ("Garen", "Syndra"):
            names = _enforce_for(champ, [_enemy("Zed", damage_type="AD",
                                                threats=["burst_ad"])])
            assert "Guardian Angel" in names

    def test_ai_situational_ineligible_item_rejected(self):
        # AP champ; AI tries to slot an AD-only item. A resolving catalog means
        # the set passes every check EXCEPT eligibility, isolating the new gate.
        class _NameCatalog:
            _ids = {"Trinity Force": 3078, "Essence Reaver": 3508,
                    "Kraken Slayer": 6672, "Bloodthirster": 3072,
                    "Phantom Dancer": 3046, "Lord Dominik's Regards": 3036,
                    "Void Staff": 3135, "Berserker's Greaves": 3006}

            def item_id(self, name):
                return self._ids.get(name)

        ctx = _ctx([_enemy("Garen", damage_type="AD")], role="middle", champion="Syndra")
        build = _dual_build()
        base = loadout_mod.from_candidate(build, ctx, "seed")
        ai = {
            "core_items": ["Trinity Force", "Essence Reaver", "Kraken Slayer"],
            "situational_items": ["Lord Dominik's Regards", "Void Staff"],  # LDR ad_only
        }
        out = loadout_mod.apply_ai_decision(base, ai, ctx, _NameCatalog(), build)
        # The ineligible AD item must not survive on an AP champion.
        assert "Lord Dominik's Regards" not in [i["name"] for i in out.items]


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
