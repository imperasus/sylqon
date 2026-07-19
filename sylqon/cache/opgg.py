"""Convert raw OP.GG MCP champion analysis data into the build dict format
used by MetaCache, bypassing the search→text→parse pipeline entirely.

Called from the FastAPI bridge (POST /api/opgg-build) which receives the
OP.GG payload delivered by Claude in the conversation via the MCP tool.
"""
from __future__ import annotations

import logging

from sylqon.data import static
from sylqon.data.catalog import Catalog

log = logging.getLogger(__name__)

SUMMONER_BY_ID = static.SPELL_BY_ID


def slot_spells(spell_ids: list[int], role: str) -> tuple[str, str]:
    """Split op.gg's two summoner ids into (spell1=D key, spell2=F key).

    D key = utility/combat spell (or Smite for junglers); F key = mobility.
    Jungle pins Smite to D; if the second spell isn't a mobility spell
    (e.g. Smite + Ignite) it still goes to F per the slotting rule.
    """
    names = [n for sid in spell_ids if (n := SUMMONER_BY_ID.get(sid))]
    mobility = [n for n in names if n in static.MOBILITY_SPELLS]
    utility = [n for n in names if n in static.UTILITY_SPELLS]

    if role == "jungle":
        # Smite is forced onto D; the other spell (mobility preferred) lands on F.
        spell2 = mobility[0] if mobility else (utility[0] if utility else static.DEFAULT_SPELL2)
        return "Smite", spell2

    spell1 = utility[0] if utility else static.DEFAULT_SPELL1_BY_ROLE.get(role, "Heal")
    spell2 = mobility[0] if mobility else static.DEFAULT_SPELL2
    return spell1, spell2

# ADC sells boots at full build → 3 situational slots (boots + core×3 + situ×3 = 7)
# All other roles keep boots all game → 2 situational slots (boots + core×3 + situ×2 = 6)
ADC_ROLES = {"bottom"}


def resolve_rune_page(page: dict) -> dict | None:
    """Resolve one rune page (id lists) into name fields, or ``None`` when any
    id is unknown. Shared by the primary build resolution and the alternative
    ``rune_page_options`` the matchup rune selector consumes."""
    primary_rune_ids: list[int] = page.get("primary_rune_ids", [])
    if len(primary_rune_ids) < 4:
        return None
    keystone = static.RUNE_BY_ID.get(primary_rune_ids[0])
    if not keystone:
        return None
    primary_runes = [static.RUNE_BY_ID.get(rid) for rid in primary_rune_ids[1:4]]
    if any(r is None for r in primary_runes):
        return None
    secondary_style = static.STYLE_BY_ID.get(page.get("secondary_page_id", 0))
    if not secondary_style:
        return None
    secondary_rune_ids: list[int] = page.get("secondary_rune_ids", [])
    secondary_runes = [static.RUNE_BY_ID.get(rid) for rid in secondary_rune_ids[:2]]
    if any(r is None for r in secondary_runes) or len(secondary_runes) < 2:
        return None
    stat_mod_ids: list[int] = page.get("stat_mod_ids", [])
    stat_shards = [static.SHARD_BY_ID.get(sid) for sid in stat_mod_ids[:3]]
    if any(s is None for s in stat_shards) or len(stat_shards) < 3:
        stat_shards = list(static.DEFAULT_SHARDS)
    return {
        "keystone": keystone,
        "primary_runes": primary_runes,
        "secondary_style": secondary_style,
        "secondary_runes": secondary_runes,
        "stat_shards": stat_shards,
    }


def _rune_page_options(payload: dict) -> list[dict]:
    """Alternative op.gg-observed rune pages with sample counts, for the matchup
    rune selector. Unresolvable pages are dropped whole; absent key → []."""
    out: list[dict] = []
    for page in payload.get("rune_page_options") or []:
        if not isinstance(page, dict):
            continue
        resolved = resolve_rune_page(page)
        if resolved is None:
            continue
        play = page.get("play") or 0
        resolved["games"] = play
        resolved["win_rate"] = round((page.get("win") or 0) / play, 3) if play else 0.0
        out.append(resolved)
    return out


def opgg_to_build(payload: dict, catalog: Catalog) -> dict | None:
    """Convert OP.GG MCP payload to MetaCache build dict.

    Expected keys (all lists of ints):
      starter_item_ids, boot_ids, core_item_ids,
      fourth_item_ids, fifth_item_ids, sixth_item_ids,
      primary_page_id, primary_rune_ids, secondary_page_id,
      secondary_rune_ids, stat_mod_ids, summoner_spell_ids, role
    Optional: core_options — [{"ids": [3 ints], "play": int, "win": int}]
      alternative core combos for the matchup core selector.
    """
    role = payload.get("role", "")
    # ADC eventually sells boots → 3 situational slots; other roles keep boots → 2
    situational_count = 3 if role in ADC_ROLES else 2

    def resolve_item(iid: int) -> dict | None:
        name = catalog.item_name(iid)
        return {"id": iid, "name": name} if name else None

    def resolve_item_with_desc(iid: int) -> dict | None:
        name = catalog.item_name(iid)
        if not name:
            return None
        return {"id": iid, "name": name, "description": catalog.item_description(name)}

    def resolve_items(ids: list[int]) -> list[dict]:
        return [r for iid in ids if (r := resolve_item(iid)) is not None]

    # Boots: op.gg's top option is the default; keep ALL listed options as a
    # pool so the loadout compiler can pick the best for the live matchup.
    all_boot_ids: list[int] = payload.get("boot_ids", [])
    boots_pool = resolve_items(all_boot_ids)
    boots_resolved = boots_pool[:1]
    boots = boots_resolved[0] if boots_resolved else None

    # Core items (exactly 3 from OP.GG core)
    core_ids: list[int] = payload.get("core_item_ids", [])
    core_items = resolve_items(core_ids)[:3]
    core_id_set = {item["id"] for item in core_items}

    # Alternative core combos (input for the matchup core selector). A combo
    # with any unresolvable item is dropped whole — a partial trio can't be
    # injected. Absent key (old cache entry / seed / MCP path) → empty list,
    # which downstream treats as "only the default core exists".
    core_options: list[dict] = []
    for opt in payload.get("core_options") or []:
        if not isinstance(opt, dict):
            continue
        resolved = resolve_items(opt.get("ids", []))
        if len(resolved) != 3:
            continue
        play = opt.get("play") or 0
        core_options.append({
            "items": resolved,
            "games": play,
            "win_rate": round((opt.get("win") or 0) / play, 3) if play else 0.0,
        })

    # Situational pool: unique items from 4th ∪ 5th ∪ 6th slots, excluding boots & core
    seen_ids: set[int] = set(core_id_set)
    if boots:
        seen_ids.add(boots["id"])
    situational_pool: list[dict] = []
    for key in ("fourth_item_ids", "fifth_item_ids", "sixth_item_ids"):
        for iid in payload.get(key, []):
            if iid not in seen_ids:
                item = resolve_item_with_desc(iid)
                if item:
                    situational_pool.append(item)
                    seen_ids.add(iid)

    # Items that appear in alternative core combos but not in the default core
    # are real, meta-proven picks on this champion — add them to the situational
    # pool so the AI's swap budget and counter enforcement can reach them even
    # when the default combo stays.
    for opt in core_options:
        for it in opt["items"]:
            if it["id"] not in seen_ids:
                item = resolve_item_with_desc(it["id"])
                if item:
                    situational_pool.append(item)
                    seen_ids.add(it["id"])

    # Default items list: boots + core + first situational_count pool items
    # ADC: 1+3+3=7 items; other roles: 1+3+2=6 items
    situ_defaults = [{"id": it["id"], "name": it["name"]}
                     for it in situational_pool[:situational_count]]
    items = boots_resolved + core_items + situ_defaults

    if len(items) < 4:
        log.warning("opgg_to_build: only %d items resolved from IDs %s",
                    len(items), all_boot_ids + core_ids)
        return None

    starting_items = resolve_items(payload.get("starter_item_ids", []))

    # Role-specific opener: junglers need their companion pet, supports the
    # quest item. Prepend it only if op.gg's starter list omits it. For jungle
    # ANY of the three companions counts, so we never stack two pets.
    role_starter = static.ROLE_STARTER_ITEMS.get(role)
    present_ids = {i["id"] for i in starting_items}
    has_starter = (
        (role == "jungle" and bool(present_ids & static.JUNGLE_COMPANION_IDS))
        or (role_starter is not None and role_starter["id"] in present_ids)
    )
    if role_starter and not has_starter:
        starting_items = [dict(role_starter)] + starting_items

    # Runes
    primary_rune_ids: list[int] = payload.get("primary_rune_ids", [])
    if len(primary_rune_ids) < 4:
        log.warning("opgg_to_build: incomplete primary runes: %s", primary_rune_ids)
        return None
    keystone = static.RUNE_BY_ID.get(primary_rune_ids[0])
    if not keystone:
        log.warning("opgg_to_build: unknown keystone id %s", primary_rune_ids[0])
        return None
    primary_runes = [static.RUNE_BY_ID.get(rid) for rid in primary_rune_ids[1:4]]
    if any(r is None for r in primary_runes):
        log.warning("opgg_to_build: unknown primary rune id in %s", primary_rune_ids[1:4])
        return None

    secondary_page_id: int = payload.get("secondary_page_id", 0)
    secondary_style = static.STYLE_BY_ID.get(secondary_page_id)
    if not secondary_style:
        log.warning("opgg_to_build: unknown secondary style id %s", secondary_page_id)
        return None
    secondary_rune_ids: list[int] = payload.get("secondary_rune_ids", [])
    secondary_runes = [static.RUNE_BY_ID.get(rid) for rid in secondary_rune_ids[:2]]
    if any(r is None for r in secondary_runes) or len(secondary_runes) < 2:
        log.warning("opgg_to_build: unknown secondary rune in %s", secondary_rune_ids)
        return None

    # Stat shards (3 IDs)
    stat_mod_ids: list[int] = payload.get("stat_mod_ids", [])
    stat_shards = [static.SHARD_BY_ID.get(sid) for sid in stat_mod_ids[:3]]
    if any(s is None for s in stat_shards) or len(stat_shards) < 3:
        log.warning("opgg_to_build: unknown shard id in %s", stat_mod_ids)
        stat_shards = list(static.DEFAULT_SHARDS)

    # Summoner spells, slotted D (utility/Smite) + F (mobility).
    spell1, spell2 = slot_spells(payload.get("summoner_spell_ids", []), role)

    # Skill max-order (display-only); keep only valid Q/W/E entries when present.
    skill_order = [s for s in (payload.get("skill_order") or [])
                   if isinstance(s, str) and s.upper() in {"Q", "W", "E"}]
    skill_order = [s.upper() for s in skill_order][:3]

    # The spells op.gg actually runs on this champion (names). Falls back to the
    # chosen combo when no alternatives were supplied (e.g. the MCP path), which
    # keeps the AI maximally conservative. Smite is always permitted for jungle.
    option_ids = payload.get("summoner_spell_options") or payload.get("summoner_spell_ids", [])
    spell_options = sorted({n for sid in option_ids if (n := SUMMONER_BY_ID.get(sid))}
                           | {spell1, spell2})

    return {
        "starting_items": starting_items,
        "boots": boots,
        "boots_pool": boots_pool,
        "core_items": core_items,
        "core_options": core_options,
        "situational_pool": situational_pool,
        "items": items,  # boots(1) + core(3) + situational(2 or 3)
        "keystone": keystone,
        "primary_runes": primary_runes,
        "secondary_style": secondary_style,
        "secondary_runes": secondary_runes,
        "stat_shards": stat_shards,
        "rune_page_options": _rune_page_options(payload),
        "spell1": spell1,
        "spell2": spell2,
        "spell_options": spell_options,
        "spell_combo_options": _spell_combo_options(payload, role),
        "skill_order": skill_order,
    }


def _spell_combo_options(payload: dict, role: str) -> list[dict]:
    """op.gg-observed summoner-spell COMBOS with sample counts, slotted D+F, for
    the matchup spell selector. Absent key → []."""
    out: list[dict] = []
    for combo in payload.get("summoner_spell_combos") or []:
        if not isinstance(combo, dict):
            continue
        ids = combo.get("ids") or []
        s1, s2 = slot_spells(ids, role)
        play = combo.get("play") or 0
        out.append({
            "spell1": s1,
            "spell2": s2,
            "games": play,
            "win_rate": round((combo.get("win") or 0) / play, 3) if play else 0.0,
        })
    return out
