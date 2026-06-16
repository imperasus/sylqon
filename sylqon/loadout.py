"""Loadout model + validation.

The AI is only ever a filter: whatever it returns is validated against the
static rune/spell/item tables here, and every invalid field falls back to the
cached/seed candidate build deterministically. The injector therefore always
receives a complete, legal loadout.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sylqon.data import static
from sylqon.data.catalog import Catalog
from sylqon.lcu.lobby import MatchContext

log = logging.getLogger(__name__)


@dataclass
class Loadout:
    items: list[dict]                  # [{"id": int, "name": str}]; 7 for ADC, 6 otherwise
    starting_items: list[dict]
    primary_style_id: int
    secondary_style_id: int
    rune_perk_ids: list[int]           # keystone + 3 primary + 2 secondary
    shard_ids: list[int]               # exactly 3, appended by the injector
    spell1: str                        # D key: utility spell (or Smite for jungle)
    spell2: str = "Flash"              # F key: mobility spell
    # Spells op.gg actually runs on this champion — the only set the AI/heuristic
    # may deviate into (per slot). Empty → fall back to the global ALLOWED lists.
    allowed_spell1: list[str] = field(default_factory=list)
    allowed_spell2: list[str] = field(default_factory=list)
    enemy_summary: str = ""
    reasoning: str = ""
    source: str = "fallback"
    name: str = ""                     # variant label, e.g. "Anti-Tank" (v2 multi-build)
    # Situational-pool fields (populated when the cached build has them)
    boots: dict | None = None
    core_items: list[dict] = field(default_factory=list)
    situational_pool: list[dict] = field(default_factory=list)


def _with_role_starter(starting_items: list[dict], role: str) -> list[dict]:
    """Guarantee the role's opener (jungle pet / support quest item) is present
    in the starting block even if the cached build omitted it. For jungle, ANY
    of the three companions counts — never stack a second pet."""
    starter = static.ROLE_STARTER_ITEMS.get(role)
    if not starter:
        return list(starting_items)
    present = {i.get("id") for i in starting_items}
    if role == "jungle" and (present & static.JUNGLE_COMPANION_IDS):
        return list(starting_items)
    if starter["id"] in present:
        return list(starting_items)
    return [dict(starter)] + list(starting_items)


def _with_starter_consumable(starting_items: list[dict]) -> list[dict]:
    """Guarantee a consumable ("drink") sits next to the opener. Keeps op.gg's
    own potion when present; otherwise appends a Health Potion so the player
    never starts without sustain."""
    if any(i.get("id") in static.STARTER_CONSUMABLE_IDS for i in starting_items):
        return list(starting_items)
    return list(starting_items) + [dict(static.STARTER_CONSUMABLE)]


def _select_boots(build: dict, ctx: MatchContext) -> dict | None:
    """Pick the best boots for THIS matchup. op.gg's meta boot is the default;
    under a clearly dominant enemy threat we swap to defensive treads (Mercury's
    vs AP / heavy CC, Plated Steelcaps vs AD). Returns None for legacy builds
    that carry no boots structure."""
    default = build.get("boots")
    if not default:
        return None
    threat = ctx.team_threat_summary()
    ap = threat.get("magic_threats", 0)
    ad = threat.get("physical_threats", 0)
    cc = threat.get("heavy_cc_count", 0)

    want: dict | None = None
    if ap >= static.BOOT_SWAP_AP_CC_MIN or cc >= static.BOOT_SWAP_AP_CC_MIN:
        want = static.MERCURYS_TREADS
    elif ad >= static.BOOT_SWAP_AD_MIN:
        want = static.PLATED_STEELCAPS
    if want is None or want["id"] == default.get("id"):
        return default  # no dominant threat, or the meta boot already fits

    # Prefer the matching option from op.gg's boot pool (carries the real name);
    # otherwise inject the universal defensive tread directly.
    for opt in build.get("boots_pool") or []:
        if opt and opt.get("id") == want["id"]:
            return dict(opt)
    log.info("Boots swapped for matchup: %s -> %s (AP=%d AD=%d CC=%d)",
             default.get("name"), want["name"], ap, ad, cc)
    return dict(want)


def _rune_ids(keystone: str, primary: list[str], secondary: list[str]) -> list[int]:
    ids = [static.KEYSTONES[keystone]]
    ids += [static.MINOR_RUNES[r] for r in primary]
    ids += [static.MINOR_RUNES[r] for r in secondary]
    return ids


def _valid_rune_block(keystone, primary, secondary, secondary_style) -> bool:
    if keystone not in static.KEYSTONES:
        return False
    p_style = static.KEYSTONE_STYLE[keystone]
    if len(primary) != 3 or len(secondary) != 2:
        return False
    if any(static.RUNE_STYLE_OF_MINOR.get(r) != p_style for r in primary):
        return False
    if secondary_style not in static.RUNE_STYLES or secondary_style == p_style:
        return False
    return all(static.RUNE_STYLE_OF_MINOR.get(r) == secondary_style for r in secondary)


def allowed_spells(build: dict, role: str) -> tuple[list[str], list[str]]:
    """The summoner spells we're allowed to slot per key, restricted to what
    op.gg actually runs on this champion (``build['spell_options']``). When the
    build carries no options (a generic seed), fall back to the global ALLOWED
    lists. The build's own default spells are always permitted."""
    options = build.get("spell_options")
    if options:
        opts = set(options)
        a1 = [s for s in static.ALLOWED_SPELL1 if s in opts]
        a2 = [s for s in static.ALLOWED_SPELL2 if s in opts]
    else:
        a1 = list(static.ALLOWED_SPELL1)
        a2 = list(static.ALLOWED_SPELL2)
    b1, b2 = build.get("spell1"), build.get("spell2")
    if role != "jungle" and b1 in static.ALLOWED_SPELL1 and b1 not in a1:
        a1.append(b1)
    if b2 in static.ALLOWED_SPELL2 and b2 not in a2:
        a2.append(b2)
    return a1 or list(static.ALLOWED_SPELL1), a2 or list(static.ALLOWED_SPELL2)


def deterministic_spells(build: dict, ctx: MatchContext,
                         allowed1: list[str] | None = None) -> tuple[str, str]:
    """Slot the two summoners: (spell1=D key, spell2=F key).

    The build's own spells (from op.gg) are the base and the default. A threat
    heuristic may override the D-key utility slot, but ONLY to a spell op.gg
    actually runs on the champion (``allowed1``) — so we never suggest a spell
    nobody uses. Jungle always keeps Smite on D. The F-key mobility slot is
    preserved from the build (Flash unless the build runs Ghost).
    """
    role = ctx.my_role
    base1 = build.get("spell1") or static.DEFAULT_SPELL1_BY_ROLE.get(role, "Heal")
    spell2 = build.get("spell2", static.DEFAULT_SPELL2)

    if role == "jungle":
        return "Smite", spell2  # Smite pinned to D; never overridden

    if allowed1 is None:
        allowed1, _ = allowed_spells(build, role)

    threats = ctx.team_threat_summary()
    squishy = role in ("middle", "bottom", "utility")
    # Override only when op.gg shows the counter-spell being used on the champ;
    # otherwise keep op.gg's default spell.
    if (threats["suppression"] or threats["heavy_cc_count"] >= 3) and squishy \
            and "Cleanse" in allowed1:
        spell1 = "Cleanse"
    elif threats["burst_ad"] and role == "utility" and "Exhaust" in allowed1:
        spell1 = "Exhaust"
    elif (threats["burst_ap"] or threats["burst_ad"]) and role == "middle" \
            and "Barrier" in allowed1:
        spell1 = "Barrier"
    else:
        spell1 = base1 if base1 in static.ALLOWED_SPELL1 else \
            static.DEFAULT_SPELL1_BY_ROLE.get(role, "Heal")
    return spell1, spell2


def from_candidate(build: dict, ctx: MatchContext, source: str) -> Loadout:
    """Deterministic loadout straight from a cached/seed build — used as the
    base and as the fallback when the AI output fails validation."""
    keystone = build["keystone"]
    a1, a2 = allowed_spells(build, ctx.my_role)
    spell1, spell2 = deterministic_spells(build, ctx, a1)

    # Matchup-aware boots: swap op.gg's default tread when a threat dominates,
    # and mirror the choice into items[0] (items = [boots, core..., situ...]).
    chosen_boots = _select_boots(build, ctx)
    items = list(build["items"])  # full list; 7 for ADC, 6 for other roles
    default_boots = build.get("boots")
    if (chosen_boots and default_boots and items
            and items[0].get("id") == default_boots.get("id")
            and chosen_boots["id"] != default_boots["id"]):
        items[0] = {"id": chosen_boots["id"], "name": chosen_boots["name"]}

    # Opener: role starter (jungle pet / support item) + a guaranteed consumable.
    starting = _with_starter_consumable(
        _with_role_starter(build.get("starting_items", []), ctx.my_role))

    return Loadout(
        items=items,
        starting_items=starting,
        primary_style_id=static.RUNE_STYLES[static.KEYSTONE_STYLE[keystone]],
        secondary_style_id=static.RUNE_STYLES[build["secondary_style"]],
        rune_perk_ids=_rune_ids(keystone, build["primary_runes"], build["secondary_runes"]),
        shard_ids=[static.STAT_SHARDS.get(s, static.STAT_SHARDS["Adaptive Force"])
                   for s in build.get("stat_shards", static.DEFAULT_SHARDS)][:3],
        spell1=spell1,
        spell2=spell2,
        allowed_spell1=a1,
        allowed_spell2=a2,
        enemy_summary=", ".join(e.name for e in ctx.enemies) or "Unknown enemies",
        source=source,
        boots=chosen_boots if chosen_boots is not None else default_boots,
        core_items=build.get("core_items", []),
        situational_pool=build.get("situational_pool", []),
    )


def apply_ai_decision(base: Loadout, ai: dict | None, ctx: MatchContext,
                      catalog: Catalog) -> Loadout:
    """Merge the AI's selections onto the candidate build, field by field,
    keeping the deterministic base wherever the AI output is invalid."""
    if not isinstance(ai, dict):
        log.info("No usable AI output; using %s build verbatim", base.source)
        return base

    out = base

    # --- Pool format: core_items + situational_items -------------------------
    has_pool = bool(base.situational_pool and base.core_items and base.boots is not None)

    if has_pool and ("core_items" in ai or "situational_items" in ai):
        pool_names = {item["name"] for item in base.situational_pool}
        default_core_names = [item["name"] for item in base.core_items]
        # Expected situational slots: total items minus boots(1) minus core items
        situational_count = len(base.items) - 1 - len(base.core_items)

        # Validate core_items: same count as default, max 1 swap, swapped item in pool
        ai_core = ai.get("core_items", [])
        core_valid = False
        final_core_names = default_core_names
        if isinstance(ai_core, list) and len(ai_core) == len(base.core_items):
            ai_core_names = [str(n) for n in ai_core]
            swaps = sum(1 for n in ai_core_names if n not in default_core_names)
            swapped_in_pool = all(
                n in pool_names for n in ai_core_names if n not in default_core_names
            )
            all_exist = all(catalog.item_id(n) is not None for n in ai_core_names)
            if swaps <= 1 and swapped_in_pool and all_exist:
                core_valid = True
                final_core_names = ai_core_names
            else:
                log.debug(
                    "AI core_items rejected (swaps=%d, pool_ok=%s, exist=%s)",
                    swaps, swapped_in_pool, all_exist,
                )

        # Validate situational_items: exact count, all from pool, no dups with boots/core
        ai_situ = ai.get("situational_items", [])
        situ_valid = False
        if isinstance(ai_situ, list) and len(ai_situ) == situational_count:
            ai_situ_names = [str(n) for n in ai_situ]
            occupied = {base.boots["name"]} | set(final_core_names)
            no_dup = len(set(ai_situ_names)) == situational_count and not (
                set(ai_situ_names) & occupied
            )
            all_in_pool = all(n in pool_names for n in ai_situ_names)
            all_exist = all(catalog.item_id(n) is not None for n in ai_situ_names)
            if no_dup and all_in_pool and all_exist:
                situ_valid = True
            else:
                log.debug(
                    "AI situational_items rejected (no_dup=%s, pool_ok=%s, exist=%s)",
                    no_dup, all_in_pool, all_exist,
                )

        if situ_valid:
            boots_item = [base.boots]
            core_resolved = [{"id": catalog.item_id(n), "name": n} for n in final_core_names]
            situ_resolved = [{"id": catalog.item_id(n), "name": n} for n in ai_situ_names]
            new_items = boots_item + core_resolved + situ_resolved
            if len(new_items) == len(base.items):
                out.items = new_items
            else:
                log.debug(
                    "AI item list length mismatch (%d vs %d); keeping baseline",
                    len(new_items), len(base.items),
                )

    # Runes: all-or-nothing block validation.
    ks = ai.get("keystone", "")
    prim = ai.get("primary_runes", [])
    sec = ai.get("secondary_runes", [])
    sec_style = ai.get("secondary_style", "")
    if _valid_rune_block(ks, prim, sec, sec_style):
        out.primary_style_id = static.RUNE_STYLES[static.KEYSTONE_STYLE[ks]]
        out.secondary_style_id = static.RUNE_STYLES[sec_style]
        out.rune_perk_ids = _rune_ids(ks, prim, sec)
    else:
        log.debug("AI rune block rejected; keeping candidate runes")

    # Stat shards: each of the 3 must belong to its row.
    shards = ai.get("stat_shards", [])
    rows = [static.SHARD_ROW_OFFENSE, static.SHARD_ROW_FLEX, static.SHARD_ROW_DEFENSE]
    if (isinstance(shards, list) and len(shards) == 3
            and all(s in rows[i] for i, s in enumerate(shards))):
        out.shard_ids = [static.STAT_SHARDS[s] for s in shards]

    # Summoner spells: the AI may only deviate into spells op.gg actually runs
    # on this champion (base.allowed_spell1/2). jungle's D-key stays Smite.
    if ctx.my_role != "jungle" and ai.get("spell1") in base.allowed_spell1:
        if ai["spell1"] != out.spell1:
            log.info("AI changed D-key spell: %s -> %s", out.spell1, ai["spell1"])
        out.spell1 = ai["spell1"]
    if ai.get("spell2") in base.allowed_spell2:
        out.spell2 = ai["spell2"]

    out.reasoning = str(ai.get("reasoning", ""))[:300]
    out.source = f"{base.source}+ollama"
    return out
