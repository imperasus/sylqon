"""Golden-set regression harness for the whole deterministic loadout pipeline.

Fixed (champion archetype × enemy comp) scenarios are compiled through the exact
deterministic path the runtime uses — matchup core selection → matchup rune-page
selection → from_candidate → counter enforcement + shard/spell/boots logic →
decisions — and the result is snapshotted. Any selector or table change that
moves an output shows up here as an explicit, reviewable diff instead of a
silent behaviour shift.

Regenerate the snapshots after an intentional change:

    SYLQON_REGEN_GOLDEN=1 python -m pytest tests/test_golden_loadouts.py -q

Fully offline: synthetic builds, stub catalog, no AI/LCU/network.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon import loadout as loadout_mod
from sylqon.analysis import core_select, decisions as decisions_mod, rune_select
from sylqon.data import static
from sylqon.lcu.lobby import EnemyProfile, MatchContext

FIXTURE = Path(__file__).parent / "fixtures" / "golden_loadouts.json"


class _StubCatalog:
    """Deterministic path needs only item_description (core-selection pool
    rebuild); AI item resolution is never exercised (ai=None)."""

    def item_description(self, name):
        return f"{name} effect"

    def item_id(self, name):  # pragma: no cover - not reached with ai=None
        return None


def _ctx(champion, role, enemies):
    return MatchContext(
        summoner_id=1, my_champion=champion, my_champion_id=1, my_role=role,
        locked=True, all_locked=True, my_turn=False, enemies=enemies,
        allies=[], fingerprint="fp",
    )


def _enemy(name, role, dmg, threats):
    return EnemyProfile(name=name, champion_id=1, role=role, side="enemy",
                        damage_type=dmg, tags=[], threats=threats)


# --- Synthetic build archetypes ------------------------------------------------

def _adc_build():
    boots = {"id": 3006, "name": "Berserker's Greaves"}
    core = [{"id": 3031, "name": "Infinity Edge"},
            {"id": 3094, "name": "Rapid Firecannon"},
            {"id": 3072, "name": "Bloodthirster"}]
    pool = [{"id": 3036, "name": "Lord Dominik's Regards"},
            {"id": 3033, "name": "Mortal Reminder"},
            {"id": 3026, "name": "Guardian Angel"},
            {"id": 3139, "name": "Mercurial Scimitar"}]
    return {
        "boots": boots, "boots_pool": [boots],
        "core_items": core, "situational_pool": pool,
        "items": [boots] + core + pool[:3],
        "core_options": [
            {"items": core, "games": 1800, "win_rate": 0.52},
            {"items": [core[0], core[1], {"id": 3036, "name": "Lord Dominik's Regards"}],
             "games": 500, "win_rate": 0.53},
        ],
        "starting_items": [dict(static.DORANS_BLADE)],
        "keystone": "Lethal Tempo",
        "primary_runes": ["Triumph", "Legend: Alacrity", "Coup de Grace"],
        "secondary_style": "Domination",
        "secondary_runes": ["Taste of Blood", "Treasure Hunter"],
        "stat_shards": ["Attack Speed", "Adaptive Force", "Health"],
        "rune_page_options": [
            {"keystone": "Lethal Tempo",
             "primary_runes": ["Triumph", "Legend: Alacrity", "Coup de Grace"],
             "secondary_style": "Domination",
             "secondary_runes": ["Taste of Blood", "Treasure Hunter"],
             "stat_shards": ["Attack Speed", "Adaptive Force", "Health"],
             "games": 1500, "win_rate": 0.52},
            {"keystone": "Lethal Tempo",
             "primary_runes": ["Triumph", "Legend: Alacrity", "Coup de Grace"],
             "secondary_style": "Resolve",
             "secondary_runes": ["Second Wind", "Bone Plating"],
             "stat_shards": ["Attack Speed", "Adaptive Force", "Health"],
             "games": 600, "win_rate": 0.53},
        ],
        "spell1": "Heal", "spell2": "Flash",
        "spell_options": ["Heal", "Flash", "Cleanse", "Barrier"],
    }


def _mage_build():
    boots = {"id": 3020, "name": "Sorcerer's Shoes"}
    core = [{"id": 3089, "name": "Rabadon's Deathcap"},
            {"id": 3157, "name": "Zhonya's Hourglass"},
            {"id": 3135, "name": "Void Staff"}]
    pool = [{"id": 3165, "name": "Morellonomicon"},
            {"id": 3102, "name": "Banshee's Veil"},
            {"id": 3116, "name": "Rylai's Crystal Scepter"}]
    return {
        "boots": boots, "boots_pool": [boots],
        "core_items": core, "situational_pool": pool,
        "items": [boots] + core + pool[:2],
        "core_options": [{"items": core, "games": 1200, "win_rate": 0.51}],
        "starting_items": [dict(static.DORANS_RING)],
        "keystone": "Electrocute",
        "primary_runes": ["Cheap Shot", "Eyeball Collection", "Ultimate Hunter"],
        "secondary_style": "Sorcery",
        "secondary_runes": ["Manaflow Band", "Transcendence"],
        "stat_shards": ["Adaptive Force", "Adaptive Force", "Health"],
        "rune_page_options": [],
        "spell1": "Ignite", "spell2": "Flash",
        "spell_options": ["Ignite", "Flash", "Barrier", "Cleanse"],
    }


def _bruiser_build():
    boots = {"id": 3047, "name": "Plated Steelcaps"},
    boots = {"id": 3047, "name": "Plated Steelcaps"}
    core = [{"id": 3078, "name": "Trinity Force"},
            {"id": 3053, "name": "Sterak's Gage"},
            {"id": 3071, "name": "Black Cleaver"}]
    pool = [{"id": 3075, "name": "Thornmail"},
            {"id": 3065, "name": "Spirit Visage"},
            {"id": 3143, "name": "Randuin's Omen"}]
    return {
        "boots": boots, "boots_pool": [boots],
        "core_items": core, "situational_pool": pool,
        "items": [boots] + core + pool[:2],
        "core_options": [{"items": core, "games": 900, "win_rate": 0.50}],
        "starting_items": [dict(static.DORANS_BLADE)],
        "keystone": "Conqueror",
        "primary_runes": ["Triumph", "Legend: Alacrity", "Last Stand"],
        "secondary_style": "Resolve",
        "secondary_runes": ["Second Wind", "Overgrowth"],
        "stat_shards": ["Adaptive Force", "Adaptive Force", "Health"],
        "rune_page_options": [],
        "spell1": "Teleport", "spell2": "Flash",
        "spell_options": ["Teleport", "Flash", "Ignite"],
    }


BUILDS = {"adc": _adc_build, "mage": _mage_build, "bruiser": _bruiser_build}

ENEMY_COMPS = {
    "balanced": [_enemy("Ahri", "middle", "AP", []),
                 _enemy("Lee Sin", "jungle", "AD", [])],
    "healing": [_enemy("Soraka", "utility", "AP", ["heavy_healing"]),
                _enemy("Aatrox", "top", "AD", ["heavy_healing"])],
    "tanks": [_enemy("Ornn", "top", "AD", ["tank"]),
              _enemy("Sion", "middle", "AD", ["tank"])],
    "burst": [_enemy("Zed", "middle", "AD", ["burst_ad"]),
              _enemy("Syndra", "top", "AP", ["burst_ap"])],
}

SCENARIOS = [
    ("adc", "bottom", "Jinx", "balanced"),
    ("adc", "bottom", "Jinx", "healing"),
    ("adc", "bottom", "Jinx", "tanks"),
    ("adc", "bottom", "Jinx", "burst"),
    ("mage", "middle", "Syndra", "healing"),
    ("mage", "middle", "Syndra", "tanks"),
    ("mage", "middle", "Syndra", "burst"),
    ("bruiser", "top", "Darius", "healing"),
    ("bruiser", "top", "Darius", "tanks"),
    ("bruiser", "top", "Darius", "burst"),
]


def _compile(build_key, role, champion, comp_key):
    cat = _StubCatalog()
    ctx = _ctx(champion, role, ENEMY_COMPS[comp_key])
    candidate = BUILDS[build_key]()
    meta = loadout_mod.from_candidate(candidate, ctx, "seed")
    cand = core_select.apply_core_selection(candidate, ctx, cat)
    cand = rune_select.apply_rune_selection(cand, ctx)
    base = loadout_mod.from_candidate(cand, ctx, "seed")
    final = loadout_mod.apply_ai_decision(base, None, ctx, cat, cand)
    final.decisions = decisions_mod.build_decisions(final, meta, cand, ctx)
    return final


def _snapshot(l) -> dict:
    return {
        "items": [i["id"] for i in l.items],
        "keystone": static.RUNE_BY_ID.get(l.rune_perk_ids[0]) if l.rune_perk_ids else None,
        "shards": [static.SHARD_BY_ID.get(s) for s in l.shard_ids],
        "spell1": l.spell1,
        "spell2": l.spell2,
        "starter": [i["id"] for i in l.starting_items],
        "first_back": [i["name"] for i in l.first_back],
        "decision_slots": [d["slot"] for d in l.decisions],
    }


def _key(s):
    return "/".join(s[:1] + s[3:] + (s[2],))


def _current():
    return {f"{bk}|{champ}|{ck}": _snapshot(_compile(bk, role, champ, ck))
            for bk, role, champ, ck in SCENARIOS}


def test_golden_loadouts_match_snapshot():
    current = _current()
    if os.environ.get("SYLQON_REGEN_GOLDEN"):
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(json.dumps(current, indent=1, sort_keys=True), encoding="utf-8")
        return
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert current == expected, (
        "Golden loadout snapshot drift. If intentional, regenerate with "
        "SYLQON_REGEN_GOLDEN=1 python -m pytest tests/test_golden_loadouts.py"
    )


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
