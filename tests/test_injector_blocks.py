"""Offline tests for the injected item-set blocks: the guaranteed consumables
block (Control Ward + potion + build-matched elixir) on both the pool and the
legacy block layouts.

Run: python -m pytest tests/test_injector_blocks.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon.data import static
from sylqon.lcu.injector import _elixir_for, build_item_blocks
from sylqon.loadout import Loadout


def _loadout(items, **kw) -> Loadout:
    defaults = dict(
        items=items,
        starting_items=[{"id": 1055, "name": "Doran's Blade"}],
        primary_style_id=8000,
        secondary_style_id=8100,
        rune_perk_ids=[8008, 9111, 9104, 8014, 8139, 8135],
        shard_ids=[5005, 5008, 5011],
        spell1="Heal",
        enemy_summary="Garen, Lux",
    )
    defaults.update(kw)
    return Loadout(**defaults)


_AD_ITEMS = [
    {"id": 3006, "name": "Berserker's Greaves"},
    {"id": 3031, "name": "Infinity Edge"},
    {"id": 3072, "name": "Bloodthirster"},
    {"id": 3036, "name": "Lord Dominik's Regards"},
]
_AP_ITEMS = [
    {"id": 3020, "name": "Sorcerer's Shoes"},
    {"id": 3089, "name": "Rabadon's Deathcap"},
    {"id": 3135, "name": "Void Staff"},
    {"id": 3157, "name": "Zhonya's Hourglass"},
]
_TANK_ITEMS = [
    {"id": 3047, "name": "Plated Steelcaps"},
    {"id": 3075, "name": "Thornmail"},
    {"id": 3065, "name": "Spirit Visage"},
]


class TestElixirChoice:
    def test_ad_build_gets_wrath(self):
        assert _elixir_for(_loadout(_AD_ITEMS)) == static.ELIXIR_OF_WRATH

    def test_ap_build_gets_sorcery(self):
        assert _elixir_for(_loadout(_AP_ITEMS)) == static.ELIXIR_OF_SORCERY

    def test_tank_build_gets_iron(self):
        assert _elixir_for(_loadout(_TANK_ITEMS)) == static.ELIXIR_OF_IRON


class TestConsumablesBlock:
    def _ids_of_last_block(self, lo):
        blocks = build_item_blocks(lo)
        return blocks[-1]["type"], [int(i["id"]) for i in blocks[-1]["items"]]

    def test_legacy_layout_ends_with_consumables(self):
        title, ids = self._ids_of_last_block(_loadout(_AD_ITEMS))
        assert "Control Ward" in title
        assert static.CONTROL_WARD["id"] in ids
        assert static.STARTER_CONSUMABLE["id"] in ids
        assert static.ELIXIR_OF_WRATH["id"] in ids

    def test_pool_layout_ends_with_consumables(self):
        pool = [{"id": 3026, "name": "Guardian Angel"}]
        lo = _loadout(
            _AD_ITEMS + [{"id": 3033, "name": "Mortal Reminder"}],
            boots=_AD_ITEMS[0],
            core_items=_AD_ITEMS[1:4],
            situational_pool=pool,
        )
        blocks = build_item_blocks(lo)
        assert "Control Ward" in blocks[-1]["type"]
        # Consumables come after the ALT pool blocks, always last.
        assert int(blocks[-1]["items"][0]["id"]) == static.CONTROL_WARD["id"]


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
