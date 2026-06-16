"""Offline tests for the item-tag build archetype classifier.

A fake catalog supplies Data Dragon item tags; the classifier should read the
damage/durability identity of a build from them. No network or real catalog.

Run: python -m pytest tests/test_build_archetype.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon.analysis.build_archetype import classify_archetype


class FakeCatalog:
    def __init__(self, table):
        self._t = table

    def items(self):
        return self._t


ITEMS = {
    "Boots": {"tags": ["Boots"]},
    # AP
    "Rabadon": {"tags": ["SpellDamage", "AbilityHaste"]},
    "Void Staff": {"tags": ["SpellDamage", "MagicPenetration"]},
    "Luden": {"tags": ["SpellDamage", "Mana"]},
    "Riftmaker": {"tags": ["SpellDamage", "Health"]},
    "Cosmic Drive": {"tags": ["SpellDamage", "Health", "AbilityHaste"]},
    # AD crit
    "Infinity Edge": {"tags": ["Damage", "CriticalStrike"]},
    "Collector": {"tags": ["Damage", "CriticalStrike", "ArmorPenetration"]},
    "Zeal": {"tags": ["Damage", "AttackSpeed", "CriticalStrike"]},
    # On-hit
    "BORK": {"tags": ["Damage", "AttackSpeed", "OnHit", "LifeSteal"]},
    "Wits End": {"tags": ["AttackSpeed", "OnHit", "SpellBlock"]},
    "Guinsoo": {"tags": ["Damage", "AttackSpeed", "OnHit"]},
    # Lethality
    "Eclipse": {"tags": ["Damage", "ArmorPenetration"]},
    "Serylda": {"tags": ["Damage", "ArmorPenetration", "AbilityHaste"]},
    "Youmuu": {"tags": ["Damage", "ArmorPenetration"]},
    # Bruiser
    "Sterak": {"tags": ["Damage", "Health"]},
    "DeadMans": {"tags": ["Damage", "Armor", "Health"]},
    "BlackCleaver": {"tags": ["Damage", "Health", "ArmorPenetration"]},
    # Tank
    "Sunfire": {"tags": ["Armor", "Health"]},
    "Thornmail": {"tags": ["Armor", "Health"]},
    "Kaenic": {"tags": ["SpellBlock", "Health"]},
}


def _cat():
    return FakeCatalog(ITEMS)


def _items(*names):
    return [{"id": i, "name": n} for i, n in enumerate(names)]


def test_ap_build():
    out = classify_archetype(_items("Boots", "Rabadon", "Void Staff", "Luden"), _cat(), "AP")
    assert out == "AP"


def test_ap_bruiser():
    out = classify_archetype(_items("Boots", "Riftmaker", "Cosmic Drive", "Rabadon"), _cat(), "AP")
    assert out == "AP Bruiser"


def test_ad_crit():
    out = classify_archetype(_items("Boots", "Infinity Edge", "Collector", "Zeal"), _cat(), "AD")
    assert out == "AD Crit"


def test_on_hit():
    out = classify_archetype(_items("Boots", "BORK", "Guinsoo", "Wits End"), _cat(), "AD")
    assert out == "On-Hit"


def test_lethality():
    out = classify_archetype(_items("Boots", "Eclipse", "Serylda", "Youmuu"), _cat(), "AD")
    assert out == "Lethality"


def test_bruiser():
    out = classify_archetype(_items("Boots", "Sterak", "DeadMans", "BlackCleaver"), _cat(), "AD")
    assert out == "Bruiser"


def test_tank():
    out = classify_archetype(_items("Boots", "Sunfire", "Thornmail", "Kaenic"), _cat(), "AD")
    assert out == "Tank"


def test_boots_ignored_and_empty_falls_back_to_damage_type():
    # nothing but boots / unknown items → fall back to the champion damage type
    assert classify_archetype(_items("Boots"), _cat(), "AP") == "AP"
    assert classify_archetype([{"id": 1, "name": "Unknown"}], _cat(), "AD") == "AD"
