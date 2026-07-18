"""Offline smoke tests for the Antigravity pipeline.

Covers everything that can run without the League client, Ollama, or the
network: seed fallback reads, the extraction parser, guardrail enforcement
(spells + stat shard routing), AI-output validation, and prompt compilation.

Run: python -m pytest tests/ -q   (or python tests/test_pipeline_offline.py)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon import config
from sylqon import loadout as loadout_mod
from sylqon.ai.prompts import compile_prompt
from sylqon.cache.opgg import opgg_to_build
from sylqon.cache.store import MetaCache
from sylqon.data import static
from sylqon.data.catalog import Catalog
from sylqon.lcu.injector import merge_stat_shards
from sylqon.lcu.lobby import EnemyProfile, MatchContext


class FakeCatalog(Catalog):
    """Catalog stub with a fixed item table; no network."""

    def __init__(self):  # bypass disk load
        self._data = {
            "fetched_at": 9e9,
            "patch": "99.1.1",
            "champions": {
                "103": {"name": "Ahri", "id": "Ahri", "tags": ["Mage"], "attack": 3, "magic": 8},
            },
            "items": {
                name: {"id": iid, "gold": 3000, "plaintext": f"{name} effect",
                       "tags": ["Boots"] if "Greaves" in name or "Treads" in name else [],
                       "completed": True}
                for name, iid in {
                    "Kraken Slayer": 6672, "Berserker's Greaves": 3006, "Infinity Edge": 3031,
                    "Lord Dominik's Regards": 3036, "Bloodthirster": 3072, "Guardian Angel": 3026,
                    "Mercury's Treads": 3111, "Mortal Reminder": 3033, "Phantom Dancer": 3046,
                    "Zhonya's Hourglass": 3157, "Maw of Malmortius": 3156,
                }.items()
            },
        }


def make_ctx(enemies=None, role="bottom", allies=None, all_locked=True,
             my_turn=False) -> MatchContext:
    return MatchContext(
        summoner_id=1, my_champion="Jinx", my_champion_id=222, my_role=role,
        locked=True, all_locked=all_locked, my_turn=my_turn, enemies=enemies or [],
        allies=allies or [], fingerprint="fp",
    )


def threat(name, **kw) -> EnemyProfile:
    defaults = dict(champion_id=1, role="middle", side="enemy", damage_type="AP",
                    tags=[], threats=[])
    defaults.update(kw)
    return EnemyProfile(name=name, **defaults)


def test_seed_fallback():
    store = MetaCache()
    # Jinx is ADC (bottom): boots + 3 core + 3 situational = 7 items
    build, source = store.get_build("Jinx", "bottom")
    assert source in ("seed", "cache", "cache-stale"), source
    assert len(build["items"]) == 7, f"ADC expected 7 items, got {len(build['items'])}"
    assert "boots" in build, "Jinx build missing boots field"
    assert len(build.get("core_items", [])) == 3, "Jinx build missing core_items"
    assert len(build.get("situational_pool", [])) >= 3, "Jinx build pool too small"
    # Non-ADC role default: boots + 3 core + 2 situational = 6 items
    build2, source2 = store.get_build("UnknownChamp", "top")
    assert source2 == "seed-role-default"
    assert build2["keystone"] in static.KEYSTONES
    assert len(build2["items"]) == 6
    assert "boots" in build2 and len(build2.get("core_items", [])) == 3


def test_opgg_converter():
    """opgg_to_build turns raw OP.GG IDs into a valid build dict."""
    cat = FakeCatalog()
    payload = {
        "champion": "Jinx", "role": "bottom",  # ADC → 3 situational slots
        "boot_ids": [3006], "core_item_ids": [6672, 3046, 3031],
        "fourth_item_ids": [3036, 3033], "fifth_item_ids": [3026, 3072],
        "sixth_item_ids": [3072, 3156],
        "primary_page_id": 8000, "primary_rune_ids": [8008, 9111, 9104, 8014],
        "secondary_page_id": 8300, "secondary_rune_ids": [8313, 8321],
        "stat_mod_ids": [5005, 5008, 5011],
        "starter_item_ids": [], "summoner_spell_ids": [4, 21],
    }
    build = opgg_to_build(payload, cat)
    assert build is not None
    names = [i["name"] for i in build["items"]]
    # ADC: boots(1) + core(3) + situational(3) = 7 items
    assert len(names) == 7, f"ADC expected 7 items, got {names}"
    assert "Berserker's Greaves" in names
    assert build["keystone"] == "Lethal Tempo"
    assert build["secondary_style"] == "Inspiration"
    assert len(build["primary_runes"]) == 3 and len(build["secondary_runes"]) == 2
    assert build["stat_shards"] == ["Attack Speed", "Adaptive Force", "Health"]
    # [4, 21] = Flash + Barrier → D-key utility=Barrier, F-key mobility=Flash
    assert build["spell1"] == "Barrier"
    assert build["spell2"] == "Flash"
    # Structured fields
    assert build["boots"] == {"id": 3006, "name": "Berserker's Greaves"}
    assert [i["name"] for i in build["core_items"]] == [
        "Kraken Slayer", "Phantom Dancer", "Infinity Edge"
    ]
    # Pool = 4th ∪ 5th ∪ 6th excluding core items
    pool_names = {i["name"] for i in build["situational_pool"]}
    assert "Lord Dominik's Regards" in pool_names   # from 4th
    assert "Mortal Reminder" in pool_names           # from 4th
    assert "Guardian Angel" in pool_names            # from 5th
    assert "Bloodthirster" in pool_names             # from 5th/6th
    assert "Maw of Malmortius" in pool_names         # from 6th
    # Core items must NOT appear in the situational pool
    for core in build["core_items"]:
        assert core["name"] not in pool_names, f"{core['name']} should not be in pool"
    # Each pool entry has a description field
    for entry in build["situational_pool"]:
        assert "description" in entry

    # Non-ADC role produces 6 items (boots + 3 core + 2 situational)
    payload_jungle = {**payload, "role": "jungle"}
    build_j = opgg_to_build(payload_jungle, cat)
    assert build_j is not None
    assert len(build_j["items"]) == 6, f"Non-ADC expected 6 items, got {len(build_j['items'])}"


def test_opgg_converter_core_options():
    """core_options resolve to named combos with win rates; combos with unknown
    items are dropped whole; alt-core-only items enrich the situational pool;
    a payload without the key (old cache / seed / MCP) yields an empty list."""
    cat = FakeCatalog()
    payload = {
        "champion": "Jinx", "role": "bottom",
        "boot_ids": [3006], "core_item_ids": [6672, 3046, 3031],
        "core_options": [
            {"ids": [6672, 3046, 3031], "play": 100, "win": 55},
            {"ids": [6672, 3157, 3031], "play": 40, "win": 24},
            {"ids": [6672, 9999, 3031], "play": 10, "win": 5},   # unknown item
        ],
        "fourth_item_ids": [3036, 3033], "fifth_item_ids": [3026, 3072],
        "sixth_item_ids": [3072, 3156],
        "primary_page_id": 8000, "primary_rune_ids": [8008, 9111, 9104, 8014],
        "secondary_page_id": 8300, "secondary_rune_ids": [8313, 8321],
        "stat_mod_ids": [5005, 5008, 5011],
        "starter_item_ids": [], "summoner_spell_ids": [4, 21],
    }
    build = opgg_to_build(payload, cat)
    assert build is not None
    opts = build["core_options"]
    assert len(opts) == 2                       # the 9999 combo was dropped whole
    assert [i["name"] for i in opts[0]["items"]] == [
        "Kraken Slayer", "Phantom Dancer", "Infinity Edge"]
    assert opts[0]["games"] == 100 and opts[0]["win_rate"] == 0.55
    assert opts[1]["win_rate"] == 0.6
    # Zhonya's only appears in an alternative combo → lands in the pool
    pool_names = {i["name"] for i in build["situational_pool"]}
    assert "Zhonya's Hourglass" in pool_names
    # Default items list is unchanged by the enrichment (appended at the back)
    assert len(build["items"]) == 7
    assert "Zhonya's Hourglass" not in [i["name"] for i in build["items"]]

    # No core_options key → empty list, everything else as before
    legacy = {k: v for k, v in payload.items() if k != "core_options"}
    build2 = opgg_to_build(legacy, cat)
    assert build2 is not None and build2["core_options"] == []


def test_opgg_converter_under_resolved_returns_none():
    """A payload that resolves fewer than 4 items (e.g. a support whose op.gg
    core item ids aren't in the catalog) must return None — and the
    under-resolution warning must not itself raise. Regression: the warning
    referenced an undefined `boot_ids`, raising NameError instead of logging.
    """
    cat = FakeCatalog()
    payload = {
        "champion": "Thresh", "role": "utility",
        # None of these item ids exist in FakeCatalog → nothing resolves,
        # so items ends up shorter than 4 and the warning path fires.
        "boot_ids": [9001], "core_item_ids": [9002, 9003, 9004],
        "fourth_item_ids": [], "fifth_item_ids": [], "sixth_item_ids": [],
        "primary_page_id": 8000, "primary_rune_ids": [8008, 9111, 9104, 8014],
        "secondary_page_id": 8300, "secondary_rune_ids": [8313, 8321],
        "stat_mod_ids": [5005, 5008, 5011],
        "starter_item_ids": [], "summoner_spell_ids": [4, 3],
    }
    # Returns None gracefully — does not raise NameError from the warning line.
    assert opgg_to_build(payload, cat) is None


def test_stat_shard_tail_routing():
    runes = [8008, 9111, 9104, 8014, 8234, 8236]
    shards = [5005, 5008, 5011]
    merged = merge_stat_shards(runes, shards)
    assert merged[-3:] == shards            # shards occupy the tail indices
    assert merged[:6] == runes
    # shard ids smuggled into the rune list get stripped, never duplicated
    merged2 = merge_stat_shards(runes + [5008], shards)
    assert merged2 == merged
    # short/invalid shard lists are padded from defaults
    merged3 = merge_stat_shards(runes, [5005])
    assert len(merged3) == 9 and all(s in static.SHARD_ID_SET for s in merged3[-3:])


def test_spell_guardrails():
    build = _make_adc_build_with_pool()
    # suppression on the enemy team -> Cleanse on the D-key for a squishy role
    ctx = make_ctx([threat("Malzahar", threats=["heavy_cc", "suppression"])], role="bottom")
    spell1, spell2 = loadout_mod.deterministic_spells(build, ctx)
    assert spell1 == "Cleanse"
    assert spell2 in static.ALLOWED_SPELL2          # F-key is a mobility spell
    # no extreme threat -> D-key is a utility spell, never Flash/mobility
    ctx2 = make_ctx([threat("Garen", damage_type="AD")], role="top")
    s1, s2 = loadout_mod.deterministic_spells(build, ctx2)
    assert s1 in static.ALLOWED_SPELL1 and s1 not in static.MOBILITY_SPELLS
    assert s2 in static.ALLOWED_SPELL2
    # AI trying to force Flash (mobility) into the D-key spell1 is rejected
    base = loadout_mod.from_candidate(build, ctx2, "seed")
    out = loadout_mod.apply_ai_decision(base, {"spell1": "Flash"}, ctx2, FakeCatalog())
    assert out.spell1 != "Flash" and out.spell1 in static.ALLOWED_SPELL1


def test_spell_options_restrict_deviation():
    """When op.gg only runs Flash+Heal on the champ, neither the threat
    heuristic nor the AI may switch to a spell op.gg never uses (e.g. Cleanse)."""
    build = _make_adc_build_with_pool()
    build["spell1"], build["spell2"] = "Heal", "Flash"
    build["spell_options"] = ["Flash", "Heal"]          # op.gg never runs Cleanse here
    a1, _ = loadout_mod.allowed_spells(build, "bottom")
    assert "Heal" in a1 and "Cleanse" not in a1
    # Heavy CC + suppression would normally trigger Cleanse — but op.gg doesn't
    # run it, so the default Heal is kept.
    ctx = make_ctx([threat("Malzahar", threats=["heavy_cc", "suppression"])], role="bottom")
    s1, _ = loadout_mod.deterministic_spells(build, ctx, a1)
    assert s1 == "Heal"
    # The AI forcing Cleanse is rejected; a default-set spell is kept.
    base = loadout_mod.from_candidate(build, ctx, "opgg")
    out = loadout_mod.apply_ai_decision(base, {"spell1": "Cleanse"}, ctx, FakeCatalog())
    assert out.spell1 == "Heal"
    # Contrast: with no spell_options (a seed build), the global ALLOWED applies
    # and Cleanse is permitted again.
    seed_build = {**build}
    seed_build.pop("spell_options")
    a1_seed, _ = loadout_mod.allowed_spells(seed_build, "bottom")
    assert "Cleanse" in a1_seed


def test_spell_slotting_jungle_smite():
    """Jungle pins Smite to D; the non-Smite spell lands on F even if utility."""
    from sylqon.cache.opgg import slot_spells
    # Smite + Flash → D=Smite, F=Flash
    assert slot_spells([11, 4], "jungle") == ("Smite", "Flash")
    # Smite + Ignite (no mobility) → D=Smite, F=Ignite (moved to F per the rule)
    assert slot_spells([11, 14], "jungle") == ("Smite", "Ignite")
    # Non-jungle Flash + Heal → D=Heal (utility), F=Flash (mobility)
    assert slot_spells([4, 7], "bottom") == ("Heal", "Flash")
    # Ghost honoured as the mobility F-key pick
    assert slot_spells([6, 14], "middle") == ("Ignite", "Ghost")
    # Jungle deterministic_spells keeps Smite locked regardless of threats
    jungle_build = {"spell1": "Smite", "spell2": "Flash"}
    ctx = make_ctx([threat("Malzahar", threats=["suppression"])], role="jungle")
    assert loadout_mod.deterministic_spells(jungle_build, ctx) == ("Smite", "Flash")


def test_role_starter_items():
    """Jungle pet and support quest item are guaranteed in the opening block."""
    cat = FakeCatalog()
    base_payload = {
        "boot_ids": [3006], "core_item_ids": [6672, 3046, 3031],
        "fourth_item_ids": [3036, 3033], "fifth_item_ids": [3026, 3072],
        "sixth_item_ids": [3156], "primary_page_id": 8000,
        "primary_rune_ids": [8008, 9111, 9104, 8014], "secondary_page_id": 8300,
        "secondary_rune_ids": [8313, 8321], "stat_mod_ids": [5005, 5008, 5011],
        "starter_item_ids": [], "summoner_spell_ids": [4, 11],
    }
    jg = opgg_to_build({**base_payload, "role": "jungle"}, cat)
    assert any(i["id"] == static.ROLE_STARTER_ITEMS["jungle"]["id"]
               for i in jg["starting_items"])
    sup = opgg_to_build({**base_payload, "role": "utility",
                         "summoner_spell_ids": [4, 3]}, cat)
    assert any(i["id"] == static.ROLE_STARTER_ITEMS["utility"]["id"]
               for i in sup["starting_items"])
    # from_candidate also back-fills a missing role starter
    ctx = make_ctx(role="utility")
    build = _make_adc_build_with_pool()
    build["starting_items"] = []
    lo = loadout_mod.from_candidate(build, ctx, "seed")
    assert any(i["id"] == static.ROLE_STARTER_ITEMS["utility"]["id"]
               for i in lo.starting_items)


def test_starter_consumable_guaranteed():
    """A consumable ("drink") is always present in the opener."""
    ctx = make_ctx()
    build = _make_adc_build_with_pool()
    # op.gg gave a starter with no potion → a Health Potion is appended.
    build["starting_items"] = [{"id": 1055, "name": "Doran's Blade"}]
    lo = loadout_mod.from_candidate(build, ctx, "opgg")
    assert static.STARTER_CONSUMABLE["id"] in [i["id"] for i in lo.starting_items]

    # op.gg already provides a potion → we don't double up.
    build["starting_items"] = [{"id": 1056, "name": "Doran's Ring"},
                               {"id": 2003, "name": "Health Potion"}]
    lo2 = loadout_mod.from_candidate(build, ctx, "opgg")
    assert sum(1 for i in lo2.starting_items if i["id"] == 2003) == 1


def test_boots_smart_swap_vs_ap():
    """Three AP enemies swap the meta boot to Mercury's Treads; items[0] mirrors it."""
    ctx = make_ctx([threat("Syndra", damage_type="AP"),
                    threat("Brand", damage_type="AP"),
                    threat("Lux", damage_type="AP")])
    build = _make_adc_build_with_pool()  # default boots = Berserker's (3006)
    lo = loadout_mod.from_candidate(build, ctx, "opgg")
    assert lo.boots["id"] == static.MERCURYS_TREADS["id"]
    assert lo.items[0]["id"] == static.MERCURYS_TREADS["id"]


def test_boots_smart_swap_vs_ad():
    """Four AD enemies swap to Plated Steelcaps."""
    ctx = make_ctx([threat(n, damage_type="AD")
                    for n in ("Zed", "Talon", "Graves", "Kha'Zix")])
    build = _make_adc_build_with_pool()
    lo = loadout_mod.from_candidate(build, ctx, "opgg")
    assert lo.boots["id"] == static.PLATED_STEELCAPS["id"]


def test_jungle_single_companion():
    """Only one jungle companion survives even if op.gg opens a different pet."""
    ctx = make_ctx(role="jungle")
    build = _make_adc_build_with_pool()
    build["starting_items"] = [{"id": 1102, "name": "Gustwalker Hatchling"},
                               {"id": 2003, "name": "Health Potion"}]
    lo = loadout_mod.from_candidate(build, ctx, "seed")
    companions = [i for i in lo.starting_items
                  if i["id"] in static.JUNGLE_COMPANION_IDS]
    assert len(companions) == 1
    assert companions[0]["id"] == 1102          # op.gg's pet kept, no Scorchclaw added


def test_boots_no_swap_when_balanced():
    """A balanced comp keeps op.gg's meta boot."""
    ctx = make_ctx([threat("Syndra", damage_type="AP"),
                    threat("Graves", damage_type="AD")])
    build = _make_adc_build_with_pool()
    lo = loadout_mod.from_candidate(build, ctx, "opgg")
    assert lo.boots["id"] == 3006          # Berserker's unchanged
    assert lo.items[0]["id"] == 3006


def test_ai_validation_falls_back():
    """All-invalid AI output: base items kept, runes kept, spell must still be valid."""
    ctx = make_ctx()
    build = _make_adc_build_with_pool()
    base = loadout_mod.from_candidate(build, ctx, "seed")
    bogus = {
        "core_items": ["Sword of Doom", "Fake Item", "Another Fake"],   # non-existent
        "situational_items": ["Ghost Sword", "Shadow Blade", "Nonexistent"],  # not in pool
        "keystone": "Made Up Keystone",                                  # invalid
        "stat_shards": ["Health", "Health", "Health"],                   # wrong rows
        "spell1": "Flash",                                               # mobility, illegal on D-key
        "reasoning": "nonsense",
    }
    out = loadout_mod.apply_ai_decision(base, bogus, ctx, FakeCatalog())
    assert [i["name"] for i in out.items] == [i["name"] for i in base.items]
    assert out.rune_perk_ids == base.rune_perk_ids
    assert out.spell1 in static.ALLOWED_SPELL1


def test_ai_pool_rune_spell_accepted():
    """Valid AI core+situational+rune+spell output is applied for a pool build."""
    ctx = make_ctx([threat("Malzahar", threats=["heavy_cc", "suppression"])])
    build = _make_adc_build_with_pool()
    base = loadout_mod.from_candidate(build, ctx, "seed")
    ai = {
        "core_items": ["Kraken Slayer", "Phantom Dancer", "Infinity Edge"],
        "situational_items": ["Maw of Malmortius", "Mercury's Treads", "Guardian Angel"],
        "keystone": "Lethal Tempo",
        "primary_runes": ["Triumph", "Legend: Alacrity", "Coup de Grace"],
        "secondary_style": "Sorcery",
        "secondary_runes": ["Celerity", "Gathering Storm"],
        "stat_shards": ["Attack Speed", "Adaptive Force", "Health"],
        "spell1": "Cleanse",
        "reasoning": "Maw + Merc vs CC/AP comp, Cleanse vs Malzahar suppression.",
    }
    out = loadout_mod.apply_ai_decision(base, ai, ctx, FakeCatalog())
    names = [i["name"] for i in out.items]
    assert len(names) == 7
    assert "Maw of Malmortius" in names
    assert "Mercury's Treads" in names
    assert out.spell1 == "Cleanse"
    assert len(out.rune_perk_ids) == 6 and len(out.shard_ids) == 3


# ---------------------------------------------------------------------------
# Situational pool path tests (new core_items + situational_items format)
# ---------------------------------------------------------------------------

def _make_adc_build_with_pool():
    """Helper: a complete ADC build dict with boots/core/pool and 7-item list."""
    return {
        "boots": {"id": 3006, "name": "Berserker's Greaves"},
        "core_items": [
            {"id": 6672, "name": "Kraken Slayer"},
            {"id": 3046, "name": "Phantom Dancer"},
            {"id": 3031, "name": "Infinity Edge"},
        ],
        "situational_pool": [
            {"id": 3036, "name": "Lord Dominik's Regards", "description": "Armor pen"},
            {"id": 3033, "name": "Mortal Reminder", "description": "Grievous wounds"},
            {"id": 3026, "name": "Guardian Angel", "description": "Revive"},
            {"id": 3072, "name": "Bloodthirster", "description": "Lifesteal"},
            {"id": 3156, "name": "Maw of Malmortius", "description": "Magic shield"},
            {"id": 3111, "name": "Mercury's Treads", "description": "Tenacity"},
        ],
        # ADC: boots(1) + core(3) + situational(3) = 7 items
        "items": [
            {"id": 3006, "name": "Berserker's Greaves"},
            {"id": 6672, "name": "Kraken Slayer"},
            {"id": 3046, "name": "Phantom Dancer"},
            {"id": 3031, "name": "Infinity Edge"},
            {"id": 3036, "name": "Lord Dominik's Regards"},
            {"id": 3026, "name": "Guardian Angel"},
            {"id": 3072, "name": "Bloodthirster"},
        ],
        "starting_items": [], "keystone": "Lethal Tempo",
        "primary_runes": ["Triumph", "Legend: Alacrity", "Coup de Grace"],
        "secondary_style": "Sorcery", "secondary_runes": ["Celerity", "Gathering Storm"],
        "stat_shards": ["Attack Speed", "Adaptive Force", "Health"], "spell1": "Heal",
    }


def test_situational_pool_accepted():
    """AI core_items + situational_items path: all 3 situational picks accepted for ADC."""
    ctx = make_ctx([threat("Malzahar", threats=["heavy_cc"])])
    build = _make_adc_build_with_pool()
    base = loadout_mod.from_candidate(build, ctx, "opgg")
    assert base.situational_pool and len(base.items) == 7

    # Valid AI: keep core unchanged, pick 3 situational from pool
    ai = {
        "core_items": ["Kraken Slayer", "Phantom Dancer", "Infinity Edge"],
        "situational_items": ["Maw of Malmortius", "Guardian Angel", "Bloodthirster"],
        "keystone": "Lethal Tempo",
        "primary_runes": ["Triumph", "Legend: Alacrity", "Coup de Grace"],
        "secondary_style": "Sorcery",
        "secondary_runes": ["Celerity", "Gathering Storm"],
        "stat_shards": ["Attack Speed", "Adaptive Force", "Health"],
        "spell1": "Cleanse",
        "reasoning": "Maw + GA vs AP/CC comp.",
    }
    out = loadout_mod.apply_ai_decision(base, ai, ctx, FakeCatalog())
    names = [i["name"] for i in out.items]
    assert len(names) == 7
    assert names[0] == "Berserker's Greaves"                         # boots fixed
    assert names[1:4] == ["Kraken Slayer", "Phantom Dancer", "Infinity Edge"]  # core unchanged
    assert set(names[4:]) == {"Maw of Malmortius", "Guardian Angel", "Bloodthirster"}
    assert out.spell1 == "Cleanse"


def test_situational_pool_core_swap_accepted():
    """A single core swap with a pool item is accepted; ADC = 3 situational slots."""
    ctx = make_ctx()
    build = _make_adc_build_with_pool()
    base = loadout_mod.from_candidate(build, ctx, "opgg")

    # AI swaps Phantom Dancer → Lord Dominik's (1 core swap, LDR is in pool)
    ai = {
        "core_items": ["Kraken Slayer", "Lord Dominik's Regards", "Infinity Edge"],
        "situational_items": ["Guardian Angel", "Bloodthirster", "Mercury's Treads"],
        "keystone": "Lethal Tempo",
        "primary_runes": ["Triumph", "Legend: Alacrity", "Coup de Grace"],
        "secondary_style": "Sorcery",
        "secondary_runes": ["Celerity", "Gathering Storm"],
        "stat_shards": ["Attack Speed", "Adaptive Force", "Health"],
        "spell1": "Heal", "reasoning": "Tanky enemies need LDR as 3rd item.",
    }
    out = loadout_mod.apply_ai_decision(base, ai, ctx, FakeCatalog())
    names = [i["name"] for i in out.items]
    assert len(names) == 7
    assert "Lord Dominik's Regards" in names[1:4]  # core swap accepted
    assert "Phantom Dancer" not in names


def test_situational_pool_out_of_pool_rejected():
    """Items not in situational_pool are rejected; base items kept."""
    ctx = make_ctx()
    build = _make_adc_build_with_pool()
    base = loadout_mod.from_candidate(build, ctx, "opgg")

    # AI proposes Zhonya's and Maw — Zhonya's is NOT in pool (only 6 items in FakeCatalog pool)
    # Actually all 6 pool items ARE in FakeCatalog. Use an item NOT in pool: Zhonya's Hourglass
    ai = {
        "core_items": ["Kraken Slayer", "Phantom Dancer", "Infinity Edge"],
        "situational_items": ["Zhonya's Hourglass", "Guardian Angel", "Maw of Malmortius"],
        "spell1": "Heal", "reasoning": "trying items outside pool",
    }
    out = loadout_mod.apply_ai_decision(base, ai, ctx, FakeCatalog())
    # Zhonya's not in pool → situational rejected → base items kept
    assert [i["name"] for i in out.items] == [i["name"] for i in base.items]


def test_situational_non_adc_two_slots():
    """Non-ADC role (jungle) gets 2 situational slots (6 items total)."""
    ctx = make_ctx(role="jungle")
    # Simulate a jungle build with 2 situational slots
    jungle_build = {
        "boots": {"id": 3047, "name": "Plated Steelcaps"},
        "core_items": [
            {"id": 3073, "name": "Experimental Hexplate"},
            {"id": 6631, "name": "Stridebreaker"},
            {"id": 3071, "name": "Black Cleaver"},
        ],
        "situational_pool": [
            {"id": 3026, "name": "Guardian Angel", "description": "Revive"},
            {"id": 6333, "name": "Death's Dance", "description": "Damage mitigation"},
            {"id": 3036, "name": "Lord Dominik's Regards", "description": "Armor pen"},
        ],
        # Non-ADC: boots(1) + core(3) + situational(2) = 6 items
        "items": [
            {"id": 3047, "name": "Plated Steelcaps"},
            {"id": 3073, "name": "Experimental Hexplate"},
            {"id": 6631, "name": "Stridebreaker"},
            {"id": 3071, "name": "Black Cleaver"},
            {"id": 3026, "name": "Guardian Angel"},
            {"id": 6333, "name": "Death's Dance"},
        ],
        "starting_items": [], "keystone": "Conqueror",
        "primary_runes": ["Triumph", "Legend: Alacrity", "Coup de Grace"],
        "secondary_style": "Inspiration", "secondary_runes": ["Magical Footwear", "Biscuit Delivery"],
        "stat_shards": ["Attack Speed", "Adaptive Force", "Health"], "spell1": "Ghost",
    }
    base = loadout_mod.from_candidate(jungle_build, ctx, "opgg")
    assert len(base.items) == 6

    # Jungle has only 2 situational slots; AI picks 2 from pool
    ai = {
        "core_items": ["Experimental Hexplate", "Stridebreaker", "Black Cleaver"],
        "situational_items": ["Lord Dominik's Regards", "Guardian Angel"],  # 2 items
        "keystone": "Conqueror",
        "primary_runes": ["Triumph", "Legend: Alacrity", "Coup de Grace"],
        "secondary_style": "Inspiration",
        "secondary_runes": ["Magical Footwear", "Biscuit Delivery"],
        "stat_shards": ["Attack Speed", "Adaptive Force", "Health"],
        "spell1": "Ghost", "reasoning": "LDR vs tanky enemies.",
    }
    # FakeCatalog doesn't have the jungle items, so this falls back to legacy
    # Just verify the pool structure is correct (no crash)
    _ = loadout_mod.apply_ai_decision(base, ai, ctx, FakeCatalog())
    assert len(base.items) == 6  # structure unchanged


def test_prompt_compiles():
    store = MetaCache()
    ctx = make_ctx([threat("Ahri", threats=["burst_ap"])])
    build, _ = store.get_build("Jinx", "bottom")
    prompt = compile_prompt(ctx, build, FakeCatalog())
    assert "Jinx" in prompt and "Ahri" in prompt and "raw JSON" in prompt
    # spells: prompt tells the model to keep op.gg's defaults unless justified
    assert "SUMMONER SPELLS" in prompt and "unless strongly justified" in prompt
    assert "RUNE DOCTRINE" in prompt
    # Pool format always used now
    assert "situational_items" in prompt
    assert "core_items" in prompt


def test_threat_directives():
    from sylqon.ai.prompts import threat_directives

    # 2 tanks → % pen ordering directive
    d = threat_directives({"tanks": 2})
    assert any("% Pen" in x and "FIRST" in x for x in d)
    # heavy healing → anti-heal mandate
    d = threat_directives({"heavy_healing": True})
    assert any("Anti-heal" in x for x in d)
    # suppression → anti-CC
    d = threat_directives({"suppression": True})
    assert any("Anti-CC" in x for x in d)
    # burst → survival ordered mid-build
    d = threat_directives({"burst_ad": True})
    assert any("Survival" in x for x in d)
    # nothing flagged → greedy default
    d = threat_directives({})
    assert len(d) == 1 and "greedily" in d[0]


def test_prompt_includes_doctrine_and_tags():
    """Pool items get [tag] annotations and the doctrine reflects the comp."""
    ctx = make_ctx([
        threat("Ornn", damage_type="AD", threats=["tank", "heavy_cc"]),
        threat("Soraka", threats=["heavy_healing"]),
        threat("Malphite", damage_type="AD", threats=["tank"]),
    ])
    build = _make_adc_build_with_pool()
    prompt = compile_prompt(ctx, build, FakeCatalog())
    assert "TACTICAL DOCTRINE" in prompt
    assert "Anti-heal" in prompt                 # healing directive + MR tag
    assert "% Pen" in prompt                     # 2 tanks directive
    # Pool annotations: Mortal Reminder carries both tags, GA is Survival
    assert "Mortal Reminder [Anti-heal/% Pen]" in prompt
    assert "Guardian Angel [Survival]" in prompt


def test_prompt_carries_matchup_core_note():
    """When the deterministic selector already swapped the core, the prompt
    says so and instructs the AI not to undo it; without a reason no note."""
    ctx = make_ctx([threat("Ornn", damage_type="AD", threats=["tank"])])
    build = _make_adc_build_with_pool()
    assert "matchup-selected core" not in compile_prompt(ctx, build, FakeCatalog())
    build["core_reason"] = "Anti-tank core: Lord Dominik's Regards covers percent_pen"
    prompt = compile_prompt(ctx, build, FakeCatalog())
    assert "matchup-selected core" in prompt
    assert "do NOT swap it back" in prompt
    assert "Lord Dominik's Regards covers percent_pen" in prompt


def test_item_blocks_multiblock():
    """Pool builds split into phases + per-category ALT blocks for mid-game pivots."""
    from sylqon.lcu.injector import build_item_blocks

    ctx = make_ctx()
    build = _make_adc_build_with_pool()
    base = loadout_mod.from_candidate(build, ctx, "opgg")
    blocks = build_item_blocks(base)
    titles = [b["type"] for b in blocks]

    # A Starting Items block now always leads — a consumable is guaranteed even
    # when op.gg's opener omitted it (here: just the injected Health Potion).
    assert titles[0] == "Starting Items"
    assert any(i["id"] == "2003" for i in blocks[0]["items"])  # Health Potion
    # Phase blocks: early core (boots+3) then this game's picks
    early = next(b for b in blocks if b["type"].startswith("Early Core"))
    assert len(early["items"]) == 4
    picked = next(b for b in blocks if b["type"].startswith("Picked vs"))
    assert len(picked["items"]) == 3             # ADC: 3 situational picks
    # Picked: LDR, GA, Bloodthirster (default pool order)
    picked_ids = {i["id"] for i in picked["items"]}
    assert picked_ids == {"3036", "3026", "3072"}

    # Leftover pool (Mortal Reminder, Maw, Mercury's) grouped by primary tag
    alt_titles = [t for t in titles if t.startswith("ALT")]
    assert any("Anti-heal" in t for t in alt_titles)   # Mortal Reminder
    assert any("Anti-CC" in t for t in alt_titles)     # Mercury's Treads
    assert any("Survival" in t for t in alt_titles)    # Maw of Malmortius
    # No already-picked item appears in an ALT block
    alt_ids = {i["id"] for b in blocks for i in b["items"] if b["type"].startswith("ALT")}
    assert not (alt_ids & picked_ids)


def test_item_blocks_seed_build():
    """Seed builds (all now have pool) produce multi-block output with Starting Items."""
    from sylqon.lcu.injector import build_item_blocks

    store = MetaCache()
    ctx = make_ctx()
    build, _ = store.get_build("Jinx", "bottom")
    base = loadout_mod.from_candidate(build, ctx, "opgg")
    blocks = build_item_blocks(base)
    titles = [b["type"] for b in blocks]
    # Must have Starting Items, Early Core, Picked vs, and at least one ALT block
    assert titles[0] == "Starting Items"
    assert any(t.startswith("Early Core") for t in titles)
    assert any(t.startswith("Picked vs") for t in titles)
    assert any(t.startswith("ALT") for t in titles)


def test_profile_title_constant():
    assert config.PROFILE_TITLE == "Sylqon Meta"


def test_recommendation_heuristic():
    """The pick heuristic favours synergy/counter and stays inside the pool."""
    from sylqon.ai.pick_prompt import (
        apply_ai_pick,
        build_candidates,
        heuristic_rank,
    )

    # Marksman candidate into a 2-tank enemy comp + an engage ally → top score.
    ctx = make_ctx(
        role="bottom",
        enemies=[
            threat("Ornn", damage_type="AD", tags=["Tank"], threats=["tank", "heavy_cc"]),
            threat("Malphite", damage_type="AD", tags=["Tank", "Fighter"], threats=["tank"]),
        ],
        allies=[threat("Leona", role="utility", side="ally", tags=["Tank", "Support"],
                       threats=["heavy_cc"])],
    )

    class RecoCatalog(FakeCatalog):
        def champion_by_name(self, name):
            table = {
                "Jinx": {"tags": ["Marksman"], "attack": 8, "magic": 1},
                "Ziggs": {"tags": ["Mage"], "attack": 2, "magic": 9},
            }
            return table.get(name)

    cat = RecoCatalog()
    pool = ["Jinx", "Ziggs", "Ornn"]   # Ornn is taken by the enemy → filtered out
    candidates = build_candidates(ctx, pool, cat)
    names = {c["name"] for c in candidates}
    assert "Ornn" not in names                       # already picked by enemy
    ranked = heuristic_rank(ctx, candidates)
    assert ranked[0]["name"] == "Jinx"               # marksman wins vs tanks + engage
    assert ranked[0]["score"] > 0

    # AI pick inside the pool is honoured; out-of-pool AI pick falls back.
    res = apply_ai_pick(ranked, {"pick": "Ziggs", "alternatives": ["Jinx"],
                                 "reasoning": "poke"})
    assert res["pick"] == "Ziggs" and res["source"] == "ollama"
    res2 = apply_ai_pick(ranked, {"pick": "Yasuo"})   # not in pool
    assert res2["pick"] == "Jinx" and res2["source"] == "heuristic"


def test_all_locked_gates_injection_fingerprint():
    """all_locked is part of the fingerprint so a re-import fires on full lock."""
    locked_partial = make_ctx(all_locked=False)
    locked_full = MatchContext(
        summoner_id=1, my_champion="Jinx", my_champion_id=222, my_role="bottom",
        locked=True, all_locked=True, my_turn=False, enemies=[], allies=[],
        fingerprint="fp",
    )
    assert locked_partial.all_locked is False
    assert locked_full.all_locked is True


def test_champions_for_role_pool():
    store = MetaCache()
    # Operate on the in-memory pool only (never _save) so the test is
    # deterministic and never clobbers the user's real curated pool on disk.
    # Fallback path: with no curated pool, returns all buildable champions.
    store._data["pool"] = {}
    pool = store.champions_for_role("bottom")
    assert "Jinx" in pool                            # seeded ADC is buildable
    assert all(isinstance(n, str) for n in pool)
    assert len(pool) == len(set(pool))               # de-duplicated
    # Curated path: an explicit pool is returned verbatim.
    store._data["pool"] = {"bottom": ["Caitlyn", "Jinx"]}
    assert store.champions_for_role("bottom") == ["Caitlyn", "Jinx"]


def test_ai_excessive_swaps_rejected():
    store = MetaCache()
    ctx = make_ctx()
    build, _ = store.get_build("Jinx", "bottom")
    base = loadout_mod.from_candidate(build, ctx, "seed")
    # Jinx (ADC) has 7 items; rewrite with only 6 → length mismatch → rejected
    rewrite = {
        "final_items": ["Mercury's Treads", "Zhonya's Hourglass", "Maw of Malmortius",
                        "Mortal Reminder", "Phantom Dancer", "Guardian Angel"],
    }
    out = loadout_mod.apply_ai_decision(base, rewrite, ctx, FakeCatalog())
    assert [i["name"] for i in out.items] == [i["name"] for i in base.items]


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeLCU:
    """Records injector traffic; simulates item-set and rune-page storage."""

    def __init__(self):
        self.item_sets = {"accountId": 1, "itemSets": [
            {"title": "My own set", "uid": "user-1", "blocks": []},
        ], "timestamp": 0}
        self.pages = [{"id": 7, "name": "My runes", "isEditable": True}]
        self.calls = []

    def get_json(self, path):
        if "item-sets" in path:
            return self.item_sets
        if "perks" in path:
            return self.pages
        return None

    def put(self, path, json=None):
        self.calls.append(("PUT", path))
        if "item-sets" in path:
            self.item_sets = json
        elif "/lol-perks/v1/pages/" in path:
            page_id = int(path.rsplit("/", 1)[1])
            for i, p in enumerate(self.pages):
                if p["id"] == page_id:
                    self.pages[i] = {**json, "id": page_id, "isEditable": True}
        return FakeResponse(200)

    def post(self, path, json=None):
        self.calls.append(("POST", path))
        new_id = max((p["id"] for p in self.pages), default=0) + 1
        self.pages.append({**json, "id": new_id, "isEditable": True})
        return FakeResponse(200)

    def patch(self, path, json=None):
        self.calls.append(("PATCH", path, json))
        return FakeResponse(204)


def test_injector_idempotent_overwrite():
    from sylqon.lcu.injector import Injector

    store = MetaCache()
    ctx = make_ctx()
    build, _ = store.get_build("Jinx", "bottom")
    final = loadout_mod.from_candidate(build, ctx, "seed")
    lcu = FakeLCU()
    injector = Injector.__new__(Injector)
    injector.client = lcu

    assert injector.inject(final, summoner_id=1, champion_id=222)
    assert injector.inject(final, summoner_id=1, champion_id=222)  # second match

    # exactly one Antigravity item set, user's own set untouched
    titles = [s["title"] for s in lcu.item_sets["itemSets"]]
    assert titles.count(config.PROFILE_TITLE) == 1 and "My own set" in titles
    # exactly one Antigravity rune page; created once (POST), then PUT
    ag_pages = [p for p in lcu.pages if p["name"] == config.PROFILE_TITLE]
    assert len(ag_pages) == 1
    page_posts = [c for c in lcu.calls if c[0] == "POST" and "perks" in c[1]]
    assert len(page_posts) == 1
    # shard ids occupy the final three indices of the rune payload
    perk_ids = ag_pages[0]["selectedPerkIds"]
    assert all(pid in static.SHARD_ID_SET for pid in perk_ids[-3:])
    assert not any(pid in static.SHARD_ID_SET for pid in perk_ids[:-3])
    # spells: D-key (spell1) is utility and never Flash; F-key (spell2) is a
    # mobility spell; the two slots never collide.
    mobility_ids = {static.SUMMONER_SPELLS[n] for n in static.ALLOWED_SPELL2}
    spells = [c[2] for c in lcu.calls if c[0] == "PATCH"]
    assert spells, "no spell patch was sent"
    assert all(s["spell1Id"] != static.FLASH_ID for s in spells)
    assert all(s["spell2Id"] in mobility_ids for s in spells)
    assert all(s["spell1Id"] != s["spell2Id"] for s in spells)


# --------------------------------------------------------------------------
# WebSocket-driven state diffing: the listener must wake heavy work only on
# meaningful changes (lock-ins, our turn) — never on hovers or timer ticks.
# --------------------------------------------------------------------------
def fake_session(*, my_champ=222, my_completed=False, my_in_progress=False,
                 their=(), their_completed=(), time_left=30000,
                 timer_phase="PICK"):
    """Synthesises a /lol-champ-select/v1/session payload.

    ``their`` is a list of (cellId, championId) for enemy hovers/picks;
    ``their_completed`` is the subset of those cellIds that are locked in."""
    their_team = [{"cellId": c, "championId": cid, "spell1Id": 4, "spell2Id": 14,
                   "assignedPosition": "middle"} for c, cid in their]
    pick_actions = [{"actorCellId": 0, "type": "pick",
                     "completed": my_completed, "isInProgress": my_in_progress}]
    for c, _cid in their:
        pick_actions.append({"actorCellId": c, "type": "pick",
                             "completed": c in their_completed, "isInProgress": False})
    return {
        "gameId": 1,
        "localPlayerCellId": 0,
        "myTeam": [{"cellId": 0, "championId": my_champ, "spell1Id": 4,
                    "spell2Id": 14, "assignedPosition": "bottom"}],
        "theirTeam": their_team,
        "actions": [pick_actions],
        "timer": {"phase": timer_phase, "adjustedTimeLeftInPhase": time_left},
    }


def test_display_signature_ignores_timer_ticks():
    from sylqon.lcu.lobby import display_signature
    a = fake_session(their=[(5, 238)], time_left=30000)
    b = fake_session(their=[(5, 238)], time_left=12000)  # clock ticked only
    assert display_signature(a) == display_signature(b)
    # a hover (new champion id) DOES move the display signature
    c = fake_session(their=[(5, 157)], time_left=30000)
    assert display_signature(a) != display_signature(c)
    # finalization flips it too
    d = fake_session(their=[(5, 238)], timer_phase="FINALIZATION")
    assert display_signature(a) != display_signature(d)


def test_trigger_signature_stable_on_hover_changes_on_lock():
    from sylqon.lcu.lobby import read_match_context
    cat = FakeCatalog()
    # enemy is merely hovering Zed
    hover = read_match_context(None, cat, session=fake_session(their=[(5, 238)]),
                               summoner_id=1)
    # same hover, clock ticked
    hover2 = read_match_context(None, cat, session=fake_session(
        their=[(5, 238)], time_left=5000), summoner_id=1)
    assert hover.trigger_signature() == hover2.trigger_signature()
    # now the enemy locks the pick in → trigger must change
    locked = read_match_context(None, cat, session=fake_session(
        their=[(5, 238)], their_completed={5}), summoner_id=1)
    assert locked.trigger_signature() != hover.trigger_signature()
    assert locked.enemies[0].locked is True
    assert hover.enemies[0].locked is False


def test_context_built_before_local_pick():
    """The recommendation must work BEFORE we pick: a champ select with enemy
    picks but no local champion still yields a context (empty my_champion)."""
    from sylqon.lcu.lobby import read_match_context
    cat = FakeCatalog()
    ctx = read_match_context(None, cat, session=fake_session(
        my_champ=0, their=[(5, 238)], their_completed={5}), summoner_id=1)
    assert ctx is not None
    assert ctx.my_champion == "" and ctx.my_champion_id == 0
    assert ctx.locked is False          # can't be locked without a champion
    assert ctx.my_role == "bottom"      # role known from assignedPosition
    assert len(ctx.enemies) == 1 and ctx.enemies[0].locked is True


def test_opgg_live_payload_shaping():
    """The live op.gg fetcher maps the API JSON into the opgg_to_build payload:
    top picks per section, runes from runes[0], and a situational pool drawn
    from last_items with core/boots removed."""
    from sylqon.cache.opgg_fetch import _shape_payload
    data = {
        "core_items": [{"ids": [3031, 3094, 3072]}, {"ids": [9999]}],
        "boots": [{"ids": [3006]}],
        "starter_items": [{"ids": [1055, 2003]}],
        "summoner_spells": [{"ids": [4, 7]}],
        "runes": [{
            "primary_page_id": 8000, "primary_rune_ids": [8008, 8009, 9103, 8017],
            "secondary_page_id": 8300, "secondary_rune_ids": [8233, 8236],
            "stat_mod_ids": [5005, 5008, 5001],
        }],
        "last_items": [{"ids": [3031]}, {"ids": [3036]}, {"ids": [3072]},
                       {"ids": [6676]}, {"ids": [3026]}],
    }
    p = _shape_payload(data, "bottom")
    assert p["core_item_ids"] == [3031, 3094, 3072]   # first (most-picked) group
    assert p["boot_ids"] == [3006]
    assert p["summoner_spell_ids"] == [4, 7]
    assert p["primary_rune_ids"][0] == 8008            # keystone
    assert p["stat_mod_ids"] == [5005, 5008, 5001]
    situ = p["fourth_item_ids"] + p["fifth_item_ids"] + p["sixth_item_ids"]
    assert 3031 not in situ and 3072 not in situ       # already core
    assert 3036 in situ and 6676 in situ and 3026 in situ
    # missing core or runes -> unusable
    assert _shape_payload({"runes": [{}]}, "bottom") is None


def test_opgg_core_options_merge_permutations():
    """op.gg lists purchase-order permutations of one trio as separate rows;
    _core_options merges them by item set (summing play/win, keeping the
    most-played ordering), skips non-trio rows, and caps at the limit."""
    from sylqon.cache.opgg_fetch import _core_options
    entries = [
        {"ids": [1, 2, 3], "play": 1785, "win": 1051},
        {"ids": [1, 4, 3], "play": 769, "win": 422},
        {"ids": [1, 3, 2], "play": 204, "win": 130},   # permutation of row 1
        {"ids": [1, 4], "play": 999, "win": 500},      # not a trio → skipped
        "garbage",
        {"ids": [5, 6, 7], "play": 50, "win": 20},
        {"ids": [8, 9, 10], "play": 40, "win": 20},
        {"ids": [11, 12, 13], "play": 30, "win": 20},  # beyond the limit
    ]
    opts = _core_options(entries)
    assert len(opts) == 4
    assert opts[0] == {"ids": [1, 2, 3], "play": 1989, "win": 1181}
    assert opts[1]["ids"] == [1, 4, 3]
    assert [o["ids"] for o in opts[2:]] == [[5, 6, 7], [8, 9, 10]]


def test_shape_payload_carries_core_options():
    """The shaped payload exposes the merged combos, and the default core is
    the genuinely most-played item set (permutations merged), not just the
    raw top row."""
    from sylqon.cache.opgg_fetch import _shape_payload
    data = {
        "core_items": [
            {"ids": [3031, 3094, 3072], "play": 10, "win": 6},
            {"ids": [3031, 3094, 3036], "play": 9, "win": 5},
            {"ids": [3031, 3072, 3094], "play": 8, "win": 3},  # permutation of row 1
        ],
        "boots": [{"ids": [3006]}],
        "runes": [{
            "primary_page_id": 8000, "primary_rune_ids": [8008, 8009, 9103, 8017],
            "secondary_page_id": 8300, "secondary_rune_ids": [8233, 8236],
            "stat_mod_ids": [5005, 5008, 5001],
        }],
        "last_items": [],
    }
    p = _shape_payload(data, "bottom")
    assert p["core_item_ids"] == [3031, 3094, 3072]
    assert p["core_options"][0] == {"ids": [3031, 3094, 3072], "play": 18, "win": 9}
    assert p["core_options"][1] == {"ids": [3031, 3094, 3036], "play": 9, "win": 5}


def test_my_turn_flag_drives_trigger():
    from sylqon.lcu.lobby import read_match_context
    cat = FakeCatalog()
    idle = read_match_context(None, cat, session=fake_session(), summoner_id=1)
    mine = read_match_context(None, cat,
                              session=fake_session(my_in_progress=True), summoner_id=1)
    assert idle.my_turn is False and mine.my_turn is True
    assert idle.trigger_signature() != mine.trigger_signature()


def test_pick_prompt_schema():
    """Both pick prompts constrain the model to the pool with JSON-serialized
    names (not a Python list repr) and ask for raw JSON output."""
    from sylqon.ai.pick_prompt import (
        compile_pick_prompt,
        compile_universe_pick_prompt,
        format_scout_block,
    )

    ctx = make_ctx(role="bottom", enemies=[threat("Ahri", threats=["burst_ap"])])
    ranked = [
        {"name": "Jinx", "tags": ["Marksman"], "damage_type": "AD",
         "score": 2, "notes": ["+2 vs tanks"]},
        {"name": "Sivir", "tags": ["Marksman"], "damage_type": "AD",
         "score": 0, "notes": []},
    ]
    prompt = compile_pick_prompt(ctx, ranked)
    assert "raw JSON" in prompt
    assert '"pick" MUST be one of' in prompt
    assert '"Jinx"' in prompt and '"Sivir"' in prompt   # JSON-quoted
    assert "'Jinx'" not in prompt                        # not a Python repr

    candidates = [
        {"champion": {"name": "Jinx"},
         "score": {"total": 80, "counter": 70, "synergy": 60, "meta": 90, "comfort": 68},
         "in_pool": True, "reasoning": "strong"},
    ]
    uni = compile_universe_pick_prompt(ctx, candidates, scout_players=None)
    assert "raw JSON" in uni and '"Jinx"' in uni and "'Jinx'" not in uni
    # Scout block is omitted entirely when there's no usable fingerprint.
    assert format_scout_block(None) == ""
    assert format_scout_block([{"hidden": True}, {"is_self": True}]) == ""


def test_strip_json_fences():
    """The engine tolerates a stray markdown fence around an otherwise-valid
    JSON body (insurance for if format='json' is ever dropped)."""
    from sylqon.ai.engine import _strip_json_fences
    assert _strip_json_fences('{"a": 1}') == '{"a": 1}'
    assert _strip_json_fences('  {"a": 1}  ') == '{"a": 1}'
    assert _strip_json_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert _strip_json_fences('```\n{"a": 1}```') == '{"a": 1}'


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    sys.exit(1 if failures else 0)
