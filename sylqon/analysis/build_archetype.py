"""Derive a build's damage/durability archetype from its item composition.

Pure and offline: reads the Data Dragon item *tags* already stored in the
catalog ("SpellDamage", "Damage", "CriticalStrike", "Armor", "SpellBlock",
"Health", "AttackSpeed", "OnHit", "ArmorPenetration"…) and aggregates them into
one short label — e.g. "AD Crit", "On-Hit", "Lethality", "AP", "AP Bruiser",
"Bruiser", "Tank". This makes the difference between build variants explicit in
the UI ("is this the AP page or the bruiser page?") without any new data source.
"""
from __future__ import annotations

_OFFENSE_AP = {"SpellDamage"}
_OFFENSE_AD = {"Damage"}
_DEFENSE = {"Armor", "SpellBlock", "Health"}


def classify_archetype(items: list[dict], catalog, damage_type: str = "") -> str:
    """Return a short archetype label for a completed-item list (boots ignored).

    ``items`` are ``{"id", "name"}`` dicts; tags are looked up by name in the
    catalog. Falls back to the champion ``damage_type`` ("AD"/"AP") when the item
    tags are too sparse to read."""
    tagsets: list[set] = []
    for it in items:
        info = catalog.items().get(it.get("name"))
        if not info:
            continue
        t = set(info.get("tags", []))
        if "Boots" in t:
            continue
        tagsets.append(t)

    if not tagsets:
        return {"AP": "AP", "AD": "AD"}.get(damage_type, "Standard")

    def cnt(*tags: str) -> int:
        want = set(tags)
        return sum(1 for t in tagsets if t & want)

    ap = cnt(*_OFFENSE_AP)
    ad = cnt(*_OFFENSE_AD)
    crit = cnt("CriticalStrike")
    aspd = cnt("AttackSpeed")
    onhit = cnt("OnHit")
    lethality = cnt("ArmorPenetration")
    defense = cnt(*_DEFENSE)
    bruiser_items = sum(1 for t in tagsets if (t & _DEFENSE) and (t & (_OFFENSE_AD | _OFFENSE_AP)))
    pure_def = sum(1 for t in tagsets if (t & _DEFENSE) and not (t & (_OFFENSE_AD | _OFFENSE_AP)))

    # Mostly defensive items with little offense → tank.
    if pure_def >= 2 and ap + ad <= 1:
        return "Tank"

    ap_lean = ap > ad or (ap == ad and damage_type == "AP")
    if ap_lean and ap >= 1:
        return "AP Bruiser" if bruiser_items >= 2 else "AP"

    if ad >= 1 or crit or aspd or onhit:
        if crit >= 2:
            return "AD Crit"
        if onhit >= 1 or aspd >= 2:
            return "On-Hit"
        if lethality >= 1 and defense <= 1:
            return "Lethality"
        if bruiser_items >= 2 or (defense >= 2 and ad >= 1):
            return "Bruiser"
        return "AD"

    return {"AP": "AP", "AD": "AD"}.get(damage_type, "Standard")
