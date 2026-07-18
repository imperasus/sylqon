"""Offline tests for AI build-variant generation (Phase 4).

Uses a fake Ollama engine and a fake catalog; no network. Verifies that:
  - without a usable engine, only the primary variant is returned;
  - AI output that produces nothing distinct is deduped away (safety fallback);
  - a valid, distinct alternative is kept and validated through the real
    loadout guardrails.

Run: python -m pytest tests/test_build_variants.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon import loadout as loadout_mod
from sylqon.ai import build_variants
from sylqon.data import static
from sylqon.lcu.lobby import EnemyProfile, MatchContext

# --- valid rune block derived from the live static tables -------------------
KEYSTONE = next(iter(static.KEYSTONES))
P_STYLE = static.KEYSTONE_STYLE[KEYSTONE]
PRIMARY = [r for r, s in static.RUNE_STYLE_OF_MINOR.items() if s == P_STYLE][:3]
SEC_STYLE = next(s for s in static.RUNE_STYLES if s != P_STYLE)
SECONDARY = [r for r, s in static.RUNE_STYLE_OF_MINOR.items() if s == SEC_STYLE][:2]
SHARDS = [static.SHARD_ROW_OFFENSE[0], static.SHARD_ROW_FLEX[0], static.SHARD_ROW_DEFENSE[0]]

ITEMS = {
    "Berserker's Greaves": 3006, "Kraken Slayer": 6672, "Infinity Edge": 3031,
    "Phantom Dancer": 3046, "Lord Dominik's Regards": 3036, "Bloodthirster": 3072,
    "Guardian Angel": 3026, "Mortal Reminder": 3033,
}


class FakeCatalog:
    def item_id(self, name):
        return ITEMS.get(name)

    def item_name(self, iid):
        return next((n for n, i in ITEMS.items() if i == iid), None)

    def item_description(self, name):
        return f"{name} effect"


class FakeEngine:
    def __init__(self, available=True, response=None):
        self._available = available
        self._response = response

    def available(self):
        return self._available

    def evaluate(self, prompt, options=None):
        return self._response


def _candidate():
    boots = {"id": 3006, "name": "Berserker's Greaves"}
    core = [{"id": 6672, "name": "Kraken Slayer"}, {"id": 3031, "name": "Infinity Edge"},
            {"id": 3046, "name": "Phantom Dancer"}]
    pool = [{"id": 3036, "name": "Lord Dominik's Regards", "description": "armor pen"},
            {"id": 3072, "name": "Bloodthirster", "description": "lifesteal"},
            {"id": 3026, "name": "Guardian Angel", "description": "revive"},
            {"id": 3033, "name": "Mortal Reminder", "description": "anti-heal"}]
    items = [boots] + core + [{"id": p["id"], "name": p["name"]} for p in pool[:3]]
    return {
        "starting_items": [{"id": 1055, "name": "Doran's Blade"}],
        "boots": boots, "core_items": core, "situational_pool": pool, "items": items,
        "keystone": KEYSTONE, "primary_runes": PRIMARY,
        "secondary_style": SEC_STYLE, "secondary_runes": SECONDARY,
        "stat_shards": SHARDS, "spell1": "Heal", "spell2": "Flash",
        "spell_options": ["Heal", "Flash", "Cleanse", "Barrier"],
    }


def _ctx():
    enemy = EnemyProfile(name="Malphite", champion_id=54, role="top", side="enemy",
                         damage_type="AP", tags=["Tank"], threats=["armor", "engage"])
    return MatchContext(summoner_id=1, my_champion="Jinx", my_champion_id=222,
                        my_role="bottom", locked=True, all_locked=True, my_turn=False,
                        enemies=[enemy], allies=[], fingerprint="fp")


def _primary(ctx, candidate):
    base = loadout_mod.from_candidate(candidate, ctx, "opgg")
    return loadout_mod.apply_ai_decision(base, None, ctx, FakeCatalog())


def test_no_engine_returns_primary_only():
    ctx, candidate = _ctx(), _candidate()
    primary = _primary(ctx, candidate)
    out = build_variants.generate_variants(ctx, candidate, FakeCatalog(),
                                           FakeEngine(available=False), primary)
    assert out == [primary]
    assert out[0].name == "Recommended"


def test_indistinct_variant_is_deduped():
    ctx, candidate = _ctx(), _candidate()
    primary = _primary(ctx, candidate)
    # AI output with wrong counts -> rejected -> equals baseline -> deduped away.
    engine = FakeEngine(response={"variants": [
        {"name": "Bogus", "core_items": ["Kraken Slayer"], "situational_items": []}
    ]})
    out = build_variants.generate_variants(ctx, candidate, FakeCatalog(), engine, primary)
    assert len(out) == 1


def test_valid_distinct_variant_is_kept():
    ctx, candidate = _ctx(), _candidate()
    primary = _primary(ctx, candidate)
    # Same core, but a different (valid) situational selection -> distinct items.
    engine = FakeEngine(response={"variants": [{
        "name": "Anti-Tank",
        "reasoning": "Malphite stacks armor",
        "core_items": ["Kraken Slayer", "Infinity Edge", "Phantom Dancer"],
        "situational_items": ["Lord Dominik's Regards", "Guardian Angel", "Mortal Reminder"],
    }]})
    out = build_variants.generate_variants(ctx, candidate, FakeCatalog(), engine, primary)
    assert len(out) == 2
    assert out[1].name == "Anti-Tank"
    alt_names = [i["name"] for i in out[1].items]
    assert "Mortal Reminder" in alt_names      # the distinguishing pick
    assert "Bloodthirster" not in alt_names     # dropped from the default order


def test_variant_prompt_lists_alternative_core_combos():
    """Real op.gg alternative combos (and the matchup-core note) reach the
    variant prompt; without core_options the section is absent."""
    ctx, candidate = _ctx(), _candidate()
    assert "ALTERNATIVE CORE COMBOS" not in build_variants.compile_variant_prompt(
        ctx, candidate, 3)

    candidate["core_options"] = [
        {"items": [{"id": 6672, "name": "Kraken Slayer"},
                   {"id": 3031, "name": "Infinity Edge"},
                   {"id": 3046, "name": "Phantom Dancer"}],   # = baseline core
         "games": 1900, "win_rate": 0.59},
        {"items": [{"id": 6672, "name": "Kraken Slayer"},
                   {"id": 3031, "name": "Infinity Edge"},
                   {"id": 3036, "name": "Lord Dominik's Regards"}],
         "games": 130, "win_rate": 0.631},
    ]
    candidate["core_reason"] = "Anti-tank core: Lord Dominik's Regards covers percent_pen"
    prompt = build_variants.compile_variant_prompt(ctx, candidate, 3)
    assert "REAL ALTERNATIVE CORE COMBOS" in prompt
    # Only the combo that differs from the baseline core is listed.
    assert "Lord Dominik's Regards — 130 games, 63.1% WR" in prompt
    assert "1900 games" not in prompt
    assert "matchup-selected core" in prompt


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
