"""Static-table integrity suite.

Every hand-curated champion name and item id/name in ``sylqon/data/static.py``
must exist in the pinned Data Dragon snapshot
(``tests/fixtures/catalog_snapshot.json``), and the rune/shard/tag tables must
be self-consistent. This is what stops the threat sets, counter tags, damage
typing and skill orders from silently rotting across patches: a rename or
removal upstream turns into a red test instead of a silently dead rule.

Regenerate the snapshot after a patch bump:

    python scripts/update_catalog_fixture.py

Fully offline: reads only the checked-in fixture.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon.data import static

_SNAP = json.loads(
    (Path(__file__).parent / "fixtures" / "catalog_snapshot.json").read_text(encoding="utf-8")
)
CHAMPIONS: set[str] = set(_SNAP["champions"])
CHAMPION_INFO: dict = _SNAP.get("champion_info", {})
ITEM_NAMES: set[str] = set(_SNAP["items"])
ITEM_IDS: set[int] = set(_SNAP["items"].values())

# Champions whose hand-authored damage type intentionally disagrees with Data
# Dragon's base attack/magic scores, because those scores don't reflect what the
# champion actually BUILDS. Qiyana is an AD assassin (lethality/AD items) whose
# DDragon magic score is an artefact of her magic-flagged ability damage.
DAMAGE_TYPE_CATALOG_EXCEPTIONS = {"Qiyana"}

# Consumables/starters are filtered out of the catalog snapshot (the runtime
# catalog drops Trinket/Consumable tags), so they are pinned here explicitly.
KNOWN_NON_CATALOG_ITEM_IDS = {
    1101, 1102, 1103,        # jungle companions
    3865,                    # World Atlas (support quest)
    2003, 2031, 2033, 2010,  # starter consumables
    2055,                    # Control Ward
    2138, 2139, 2140,        # elixirs
}


def _assert_champions(names, table_name):
    unknown = sorted(set(names) - CHAMPIONS)
    assert not unknown, (
        f"{table_name} contains names missing from the Data Dragon catalog "
        f"(patch {_SNAP['patch']}): {unknown}"
    )


# ---------------------------------------------------------------------------
# Champion-name validity
# ---------------------------------------------------------------------------

class TestChampionNames:
    def test_threat_sets(self):
        for table in ("HEAVY_CC_CHAMPS", "SUPPRESSION_CHAMPS", "HIGH_BURST_AD",
                      "HIGH_BURST_AP", "HEAVY_HEALING", "HEAVY_POKE",
                      "HEAVY_TANK", "SPLIT_PUSH_CHAMPS"):
            _assert_champions(getattr(static, table), table)

    def test_champion_damage_type(self):
        _assert_champions(static.CHAMPION_DAMAGE_TYPE, "CHAMPION_DAMAGE_TYPE")

    def test_skill_max_order(self):
        _assert_champions(static.SKILL_MAX_ORDER, "SKILL_MAX_ORDER")

    def test_rune_archetypes(self):
        _assert_champions(static.CHAMPION_RUNE_ARCHETYPES, "CHAMPION_RUNE_ARCHETYPES")

    def test_ignite_kill_laners(self):
        _assert_champions(static.IGNITE_KILL_LANERS, "IGNITE_KILL_LANERS")

    def test_suppression_is_subset_of_heavy_cc(self):
        # A suppressor is by definition a heavy-CC threat too.
        assert static.SUPPRESSION_CHAMPS <= static.HEAVY_CC_CHAMPS


# ---------------------------------------------------------------------------
# Item id/name validity
# ---------------------------------------------------------------------------

class TestItemTables:
    def test_counter_tag_ids_exist(self):
        unknown = sorted(iid for iid in static.ITEM_COUNTER_TAGS
                         if iid not in ITEM_IDS and iid not in KNOWN_NON_CATALOG_ITEM_IDS)
        assert not unknown, (
            f"ITEM_COUNTER_TAGS ids missing from catalog patch {_SNAP['patch']}: {unknown}"
        )

    def test_class_restriction_names_exist(self):
        unknown = sorted(set(static.ITEM_CLASS_RESTRICTION) - ITEM_NAMES)
        assert not unknown, (
            f"ITEM_CLASS_RESTRICTION names missing from catalog patch "
            f"{_SNAP['patch']} (rename upstream silently disables the rule): {unknown}"
        )

    def test_defensive_boots_match_catalog(self):
        for const in (static.MERCURYS_TREADS, static.PLATED_STEELCAPS):
            assert _SNAP["items"].get(const["name"]) == const["id"], (
                f"{const['name']} id/name pair out of sync with the catalog"
            )

    def test_lane_layer_items_match_catalog(self):
        consts = [static.DORANS_BLADE, static.DORANS_SHIELD, static.DORANS_RING]
        consts += [v for by_class in static.COUNTER_COMPONENTS.values()
                   for v in by_class.values()]
        consts += list(static.LANE_RESIST_COMPONENT.values())
        for const in consts:
            assert _SNAP["items"].get(const["name"]) == const["id"], (
                f"{const['name']} id/name pair out of sync with the catalog"
            )

    def test_counter_components_cover_damage_classes(self):
        for tag, by_class in static.COUNTER_COMPONENTS.items():
            assert set(by_class) == {"ad", "ap", "mixed"}, tag

    def test_counter_tags_have_display_info(self):
        used = {t for tags in static.ITEM_COUNTER_TAGS.values() for t in tags}
        missing = sorted(used - set(static.COUNTER_TAG_INFO))
        assert not missing, f"COUNTER_TAG_INFO missing labels for tags: {missing}"

    def test_class_restriction_values_legal(self):
        assert set(static.ITEM_CLASS_RESTRICTION.values()) <= {
            "ad_only", "ap_only", "universal"}

    def test_champion_damage_type_values_legal(self):
        assert set(static.CHAMPION_DAMAGE_TYPE.values()) <= {"ad", "ap", "mixed"}

    def test_champion_damage_type_not_contradicted_by_catalog(self):
        """An 'ad' champion whose catalog base is decisively magic (or vice
        versa) is almost certainly a stale/renamed entry — flag it unless it's
        a documented hybrid-scaling exception."""
        contradictions = []
        for champ, dt in static.CHAMPION_DAMAGE_TYPE.items():
            info = CHAMPION_INFO.get(champ)
            if not info or champ in DAMAGE_TYPE_CATALOG_EXCEPTIONS:
                continue
            a, m = info.get("attack", 0), info.get("magic", 0)
            if dt == "ad" and m >= a + 3:
                contradictions.append(f"{champ} typed 'ad' but catalog magic={m} attack={a}")
            if dt == "ap" and a >= m + 3:
                contradictions.append(f"{champ} typed 'ap' but catalog attack={a} magic={m}")
        assert not contradictions, contradictions


# ---------------------------------------------------------------------------
# Generated (catalog-derived) counter tags
# ---------------------------------------------------------------------------

class TestGeneratedItemTags:
    def test_generated_ids_exist_in_catalog(self):
        gen = static._load_generated_item_tags()
        unknown = sorted(iid for iid in gen
                         if iid not in ITEM_IDS and iid not in KNOWN_NON_CATALOG_ITEM_IDS)
        assert not unknown, (
            f"generated_item_tags.json ids missing from catalog: {unknown}"
        )

    def test_generated_tags_are_high_precision_only(self):
        gen = static._load_generated_item_tags()
        used = {t for tags in gen.values() for t in tags}
        assert used <= {"armor", "mr", "anti_cc"}, (
            f"generation must stay to the precise defensive layer, got: {used}"
        )

    def test_merge_never_drops_a_manual_tag(self):
        for iid, manual in static.ITEM_COUNTER_TAGS_MANUAL.items():
            merged = static.ITEM_COUNTER_TAGS[iid]
            assert set(manual) <= set(merged), iid
            # manual tags keep their leading (display-priority) position
            assert merged[:len(manual)] == manual, iid

    def test_merge_adds_generated_coverage(self):
        # Locket of the Iron Solari (3190) is generated-only armor/mr — present
        # in the merged table though absent from the hand table.
        gen = static._load_generated_item_tags()
        gen_only = set(gen) - set(static.ITEM_COUNTER_TAGS_MANUAL)
        assert gen_only, "expected generation to add items beyond the hand table"
        for iid in gen_only:
            assert set(static.ITEM_COUNTER_TAGS[iid]) == set(gen[iid])


# ---------------------------------------------------------------------------
# Rune / shard / skill self-consistency
# ---------------------------------------------------------------------------

class TestRuneAndShardConsistency:
    def test_every_keystone_has_a_style(self):
        assert set(static.KEYSTONES) == set(static.KEYSTONE_STYLE)

    def test_keystone_styles_are_valid(self):
        assert set(static.KEYSTONE_STYLE.values()) <= set(static.RUNE_STYLES)

    def test_every_minor_rune_has_a_style(self):
        assert set(static.MINOR_RUNES) == set(static.RUNE_STYLE_OF_MINOR)

    def test_rune_counter_tag_names_are_real_runes(self):
        unknown = sorted(set(static.RUNE_COUNTER_TAGS) - set(static.MINOR_RUNES))
        assert not unknown, f"RUNE_COUNTER_TAGS names not in MINOR_RUNES: {unknown}"

    def test_rune_requirement_rules_reference_known_tags(self):
        known_tags = {t for tags in static.RUNE_COUNTER_TAGS.values() for t in tags}
        for _threat_key, tag in static.RUNE_REQUIREMENT_RULES:
            assert tag in known_tags, f"rune requirement tag '{tag}' unmapped"

    def test_shard_rows_are_known_shards(self):
        for row in (static.SHARD_ROW_OFFENSE, static.SHARD_ROW_FLEX,
                    static.SHARD_ROW_DEFENSE):
            assert set(row) <= set(static.STAT_SHARDS)

    def test_default_shards_are_row_valid(self):
        rows = [static.SHARD_ROW_OFFENSE, static.SHARD_ROW_FLEX,
                static.SHARD_ROW_DEFENSE]
        assert len(static.DEFAULT_SHARDS) == 3
        for i, name in enumerate(static.DEFAULT_SHARDS):
            assert name in rows[i]

    def test_deprecated_keystones_absent(self):
        # Removed from the game years ago; injecting their perk ids would be
        # silently dropped by the LCU, leaving a broken rune page.
        for dead in ("Deathfire Touch", "Klepto", "Kleptomancy", "Predator"):
            assert dead not in static.KEYSTONES

    def test_skill_orders_are_valid(self):
        for champ, order in static.SKILL_MAX_ORDER.items():
            assert len(order) == 3 and len(set(order)) == 3, champ
            assert set(order) == {"Q", "W", "E"}, champ

    def test_role_aliases_canonical(self):
        assert set(static.ROLE_ALIASES.values()) <= {
            "top", "jungle", "middle", "bottom", "utility"}


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
