"""Generate high-precision counter tags for completed items from the Data
Dragon catalog, so the hand-curated ITEM_COUNTER_TAGS table no longer has to
enumerate every defensive resist item by hand.

We ONLY generate the tags that DDragon's coarse item-tag set can identify
without effect-level knowledge — the defensive-resist and tenacity layer:

    armor    ← a pure defensive item that itemises Armor + Health
    mr       ← a pure defensive item that itemises Magic Resist + Health
    anti_cc  ← any item that grants Tenacity

Effect-level tags (anti_heal, percent_pen, tank_shred, anti_burst,
anti_suppression) require reading what the item DOES, not just its stat
categories, so those stay in the hand table. The runtime UNIONS the generated
tags with the manual ones (loadout / static), so generation only ever ADDS
coverage — it can never drop a hand-authored tag.

Re-run after a patch bump (same cadence as the catalog fixture):

    python scripts/generate_item_tags.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sylqon.data.catalog import Catalog  # noqa: E402

# Stat categories that mark an item as offensive — a pure defensive resist
# item carries none of these.
OFFENSIVE = {"Damage", "CriticalStrike", "AttackSpeed", "SpellDamage",
             "LifeSteal", "SpellVamp", "OnHit", "ArmorPenetration",
             "MagicPenetration"}


def _tags_for(item: dict) -> list[str]:
    tags = set(item.get("tags", []))
    if "Boots" in tags:
        return []
    out: list[str] = []
    offensive = bool(tags & OFFENSIVE)
    if "Tenacity" in tags:
        out.append("anti_cc")
    if not offensive and "Health" in tags and "Armor" in tags:
        out.append("armor")
    if not offensive and "Health" in tags and "SpellBlock" in tags:
        out.append("mr")
    return out


def main() -> int:
    cat = Catalog()
    items = cat.items()
    if not items:
        print("Catalog cache is empty; run the app once to fetch it.")
        return 1

    generated: dict[str, list[str]] = {}
    for name, item in items.items():
        if not item.get("completed"):
            continue
        tags = _tags_for(item)
        if tags:
            generated[str(item["id"])] = tags

    out = ROOT / "sylqon" / "data" / "generated_item_tags.json"
    out.write_text(
        json.dumps({str(k): generated[k] for k in sorted(generated, key=int)},
                   indent=1),
        encoding="utf-8")
    print(f"Wrote {out}: {len(generated)} items tagged "
          f"(patch {cat.patch})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
