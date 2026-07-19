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
    # Lane-counter layer (populated by from_candidate when a lane opponent is
    # identifiable): cheap first-recall counter components + display context.
    first_back: list[dict] = field(default_factory=list)
    lane_opponent_name: str = ""
    starter_reason: str = ""


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


def _safe_threat(ctx: MatchContext) -> dict:
    """Threat summary as a plain dict, tolerant of stub/mocked contexts.

    The threat-aware item/rune/shard logic runs even when ``ai`` is missing, so
    a bare test double whose ``team_threat_summary()`` returns a non-dict must
    degrade to "no threat" rather than raise or read truthy mock values."""
    try:
        summary = ctx.team_threat_summary()
    except Exception:  # pragma: no cover - defensive
        return {}
    return summary if isinstance(summary, dict) else {}


def _strong_threat(threat: dict) -> bool:
    """A genuinely strong enemy threat that can justify deviating the keystone
    from the meta op.gg page (assassins/burst, chain CC, suppression)."""
    return bool(
        threat.get("burst_ad")
        or threat.get("burst_ap")
        or threat.get("suppression")
        or threat.get("heavy_cc_count", 0) >= 3
    )


# --- Counter-item enforcement -------------------------------------------------
# Threat condition -> the counter tag(s) that MUST appear somewhere in the final
# build, in priority order. ``urgent`` items are inserted at the front of the
# situational block (they win fights early); the rest go at the back. This is the
# code-level mirror of ``prompts.threat_directives``.

def _item_eligible_for_champion(item_name: str, champion: str) -> bool:
    """Whether an item's damage class fits the champion's damage profile.

    Keeps counter-item enforcement (and AI item picks) type-correct: an AP-only
    item never lands on a pure-AD champion and vice-versa. Unknown champion →
    "mixed" and unknown item → "universal" — both permissive, so we degrade to
    the old behaviour rather than over-restricting."""
    champ_type = static.CHAMPION_DAMAGE_TYPE.get(champion, "mixed")
    if champ_type == "mixed":
        return True  # hybrids/tanks/supports: any class is fine
    item_class = static.ITEM_CLASS_RESTRICTION.get(item_name, "universal")
    if item_class == "ad_only":
        return champ_type == "ad"
    if item_class == "ap_only":
        return champ_type == "ap"
    return True  # universal (or unknown label) → always eligible


def _counter_requirements(threat: dict) -> list[tuple[set[str], bool]]:
    reqs: list[tuple[set[str], bool]] = []
    if threat.get("heavy_healing"):
        reqs.append(({"anti_heal"}, True))
    if threat.get("tanks", 0) >= 2:
        # %Pen or %HP shred must arrive early vs a stacked frontline.
        reqs.append(({"percent_pen", "tank_shred"}, True))
    if threat.get("suppression"):
        # Only the QSS/Mercurial active removes suppression — tenacity boots,
        # Mikael's and the Cleanse summoner do not, so this requirement accepts
        # the narrow anti_suppression tag only.
        reqs.append(({"anti_suppression"}, True))
    if threat.get("heavy_cc_count", 0) >= 3:
        reqs.append(({"anti_cc"}, True))
    if threat.get("burst_ad") or threat.get("burst_ap"):
        reqs.append(({"anti_burst"}, True))
    if threat.get("physical_threats", 0) >= 4:
        reqs.append(({"armor"}, False))
    if threat.get("magic_threats", 0) >= 3:
        reqs.append(({"mr"}, False))
    return reqs


def _least_important_slot(situ: list[dict], required_union: set[str],
                          protected_front: int) -> int | None:
    """Index of the situational slot safest to drop: the last (greediest) pick
    that does NOT itself carry a still-required counter tag, scanning right→left
    and never touching the urgent counters already inserted at the front. Returns
    None when every remaining slot is load-bearing (so we never trade away one
    mandated tag for another)."""
    for idx in range(len(situ) - 1, protected_front - 1, -1):
        tags = static.ITEM_COUNTER_TAGS.get(situ[idx].get("id", 0), ())
        if not (set(tags) & required_union):
            return idx
    return None


def _enforce_counter_items(base: Loadout, items: list[dict], build: dict,
                           ctx: MatchContext, catalog: Catalog) -> list[dict]:
    """Code-level guarantee that threat-mandated counter items are present.

    For every counter tag the enemy comp demands but the current build misses,
    swap the least-important (greedy/damage) situational slot for a pool item
    carrying that tag — urgent tags (anti-heal / %pen / anti-CC / survival) move
    to the front of the situational block, defensive preferences to the back.

    Boots (slot 0) and core slots are never touched — defensive boots are
    ``_select_boots``' job. Returns ``items`` unchanged whenever no threat
    mandates a swap, the build has no editable situational structure, or the
    pool can't satisfy a tag — so the result is never illegal or shorter."""
    # Lane requirements come first (the laning phase is decided early), then
    # the team-level mandates. Lazy import: lane_counter imports this module.
    from sylqon.analysis.lane_counter import combined_requirements
    reqs = combined_requirements(ctx)
    if not reqs:
        return items

    pool = (build.get("situational_pool") if isinstance(build, dict) else None) \
        or base.situational_pool
    if not pool or not base.core_items:
        return items  # legacy flat build: no boots+core+situational structure

    n_fixed = 1 + len(base.core_items)  # boots + core stay put
    if n_fixed >= len(items):
        return items  # no situational slots to adjust

    head = list(items[:n_fixed])
    situ = list(items[n_fixed:])

    def tags_of(item_id: int | None) -> set[str]:
        return set(static.ITEM_COUNTER_TAGS.get(item_id or 0, ()))

    # Pool items keyed by id, filtered to the champion's damage class (resolving
    # via catalog only if a pool entry lacks an id). This is what prevents an AP
    # item being enforced onto an AD champion (or vice-versa).
    champion = getattr(ctx, "my_champion", "") or ""
    pool_by_id: dict[int, dict] = {}
    for it in pool:
        name = it.get("name", "")
        iid = it.get("id")
        if iid is None and catalog is not None:
            iid = catalog.item_id(name)
        if iid is None:
            continue
        if not _item_eligible_for_champion(name, champion):
            log.debug("Counter item %s not eligible for %s (%s); skipping pool entry",
                      name, champion, static.CHAMPION_DAMAGE_TYPE.get(champion, "mixed"))
            continue
        pool_by_id.setdefault(iid, {"id": iid, "name": name})

    required_union: set[str] = set().union(*(tags for tags, _ in reqs))
    urgent_front = 0  # how many urgent counters we've pinned to the front so far

    for accepted, urgent in reqs:
        if any(tags_of(it.get("id")) & accepted for it in head + situ):
            continue  # already covered (boots/core count too)
        in_build = {it.get("id") for it in head} | {s.get("id") for s in situ}
        replacement = next(
            (it for iid, it in pool_by_id.items()
             if iid not in in_build and tags_of(iid) & accepted),
            None,
        )
        if replacement is None:
            continue  # pool can't cover this tag — leave the build as-is
        drop = _least_important_slot(situ, required_union, urgent_front)
        if drop is None:
            continue  # every slot is load-bearing; don't break existing cover
        situ.pop(drop)
        if urgent:
            situ.insert(urgent_front, replacement)
            urgent_front = min(urgent_front + 1, len(situ))
        else:
            situ.append(replacement)

    result = head + situ
    if len(result) != len(items):  # pragma: no cover - defensive invariant
        log.debug("Counter enforcement changed item count; keeping original build")
        return items
    if [i.get("id") for i in result] != [i.get("id") for i in items]:
        log.info("Counter items enforced for matchup: %s",
                 [i.get("name") for i in result[n_fixed:]])
    return result


# --- Threat-aware stat shards -------------------------------------------------

def _clamp_shard(value: str, row: list[str], fallback: str) -> str:
    """Keep a shard name inside its legal row, preferring the op.gg fallback."""
    if value in row:
        return value
    if fallback in row:
        return fallback
    return row[0]


def _acceptable_defense_shards(threat: dict) -> set[str]:
    """Defense-row shards that are *not worse* than the computed default for this
    comp. The AI's defense pick is only honoured when it lands in this set,
    otherwise the threat-aware computed shard wins (e.g. never let pure Health
    Scaling replace Tenacity into chain-CC / suppression)."""
    ap = threat.get("magic_threats", 0)
    ad = threat.get("physical_threats", 0)
    # Tenacity does nothing against suppression, so only real chain CC forces
    # the tenacity shard; a lone suppressor is answered item-side (QSS).
    heavy_cc = threat.get("heavy_cc_count", 0) >= 3
    ap_heavy = ap >= 3 and ap > ad
    ad_heavy = ad >= 4 and ad >= ap
    if heavy_cc:
        return {"Tenacity and Slow Resist"}
    if ap_heavy:
        return {"Health Scaling", "Tenacity and Slow Resist"}
    if ad_heavy:
        return {"Health", "Tenacity and Slow Resist", "Health Scaling"}
    return set(static.SHARD_ROW_DEFENSE)


def _compute_default_shards(threat: dict, base_shards: list[str]) -> list[str]:
    """Threat-aware meta-default shard trio (offense / flex / defense).

    Offense stays on the op.gg pick; the flex and (mainly) defense rows adapt to
    the enemy AD/AP balance and CC load. Always returns a valid, in-row trio, so
    it is a safe default even when the AI gives no shards at all."""
    off, flex, dfn = base_shards[0], base_shards[1], base_shards[2]
    ap = threat.get("magic_threats", 0)
    ad = threat.get("physical_threats", 0)
    # Suppression deliberately does NOT force tenacity here: tenacity has no
    # effect on suppression duration — that threat is answered by the QSS item
    # mandate in _counter_requirements.
    heavy_cc = threat.get("heavy_cc_count", 0) >= 3
    ap_heavy = ap >= 3 and ap > ad
    ad_heavy = ad >= 4 and ad >= ap

    if ap_heavy:                       # decisively magic damage → extra HP scaling
        flex = "Health Scaling"
    if heavy_cc:                       # chain CC / suppression → tenacity over raw HP
        dfn = "Tenacity and Slow Resist"
    elif ap_heavy:
        dfn = "Health Scaling"
    elif ad_heavy:                     # burst AD wants tenacity to survive the combo
        dfn = "Tenacity and Slow Resist" if threat.get("burst_ad") else "Health"
    # balanced comp → keep the op.gg defense shard.

    return [
        _clamp_shard(off, static.SHARD_ROW_OFFENSE, base_shards[0]),
        _clamp_shard(flex, static.SHARD_ROW_FLEX, base_shards[1]),
        _clamp_shard(dfn, static.SHARD_ROW_DEFENSE, base_shards[2]),
    ]


def _base_shard_names(out: Loadout, candidate_build: dict | None) -> list[str]:
    """The op.gg/meta default shard names (offense/flex/defense). Prefers the
    candidate build's ``stat_shards`` and falls back to the page already on the
    loadout (set by :func:`from_candidate`), then the global default."""
    if isinstance(candidate_build, dict):
        shards = candidate_build.get("stat_shards")
        if (isinstance(shards, list) and len(shards) == 3
                and all(isinstance(s, str) for s in shards)):
            return list(shards)
    names = [static.SHARD_BY_ID.get(i) for i in (out.shard_ids or [])]
    if len(names) == 3 and all(names):
        return names  # type: ignore[return-value]
    return list(static.DEFAULT_SHARDS)


def _valid_rune_block(
    keystone: str,
    primary: list[str],
    secondary: list[str],
    secondary_style: str,
    rune_pool: dict | None = None,
) -> bool:
    """Validate a rune block.

    When rune_pool is provided (champion-specific archetype), additionally
    checks that:
    - keystone is in rune_pool['keystone_options']
    - secondary_style is in rune_pool['secondary_style_options']
    - all secondary runes are in rune_pool['secondary_minor_options']

    The primary tree / style-consistency check always runs regardless of pool.
    """
    if keystone not in static.KEYSTONES:
        return False
    p_style = static.KEYSTONE_STYLE[keystone]
    if len(primary) != 3 or len(secondary) != 2:
        return False
    if any(static.RUNE_STYLE_OF_MINOR.get(r) != p_style for r in primary):
        return False
    if secondary_style not in static.RUNE_STYLES or secondary_style == p_style:
        return False
    if not all(static.RUNE_STYLE_OF_MINOR.get(r) == secondary_style for r in secondary):
        return False

    if rune_pool is not None:
        if keystone not in rune_pool["keystone_options"]:
            return False
        if secondary_style not in rune_pool["secondary_style_options"]:
            return False
        if not all(r in rune_pool["secondary_minor_options"] for r in secondary):
            return False

    return True


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
    # Cleanse does NOT remove suppression (Malzahar/Warwick/Urgot/Skarner R) —
    # only the QSS/Mercurial item active does, and that is guaranteed by the
    # item-side anti_suppression mandate. Cleanse is only worth the summoner
    # slot into genuine chain CC (3+ heavy-CC enemies).
    if threats["heavy_cc_count"] >= 3 and squishy and "Cleanse" in allowed1:
        spell1 = "Cleanse"
    elif threats["burst_ad"] and role == "utility" and "Exhaust" in allowed1:
        spell1 = "Exhaust"
    elif (threats["burst_ap"] or threats["burst_ad"]) and role == "middle" \
            and "Barrier" in allowed1:
        spell1 = "Barrier"
    elif _enemy_poke_count(ctx) >= 2 and role == "middle" and "Barrier" in allowed1:
        # Heavy poke comp chunks a mid carry before the fight — Barrier survives
        # the harass (only when op.gg actually runs it on the champion).
        spell1 = "Barrier"
    elif _kill_pressure_ignite(ctx, role, allowed1):
        # Winnable lane on a kill-threat champion: Ignite converts the lead into
        # kills. Lower priority than every defensive branch — survival first.
        spell1 = "Ignite"
    else:
        spell1 = base1 if base1 in static.ALLOWED_SPELL1 else \
            static.DEFAULT_SPELL1_BY_ROLE.get(role, "Heal")
    return spell1, spell2


def _kill_pressure_ignite(ctx: MatchContext, role: str,
                          allowed1: list[str]) -> bool:
    """Whether to take Ignite for lane kill pressure.

    True only when: the role is top/mid, our champion's wincon is kill pressure
    (``IGNITE_KILL_LANERS``), op.gg actually runs Ignite on it (``allowed1``),
    and the lane opponent is a killable target — NOT a heavy tank or a sustain
    champion who laughs off the ignite-dive. Degrades to False on any stub ctx.
    """
    if role not in ("top", "middle") or "Ignite" not in allowed1:
        return False
    champ = getattr(ctx, "my_champion", "") or ""
    if champ not in static.IGNITE_KILL_LANERS:
        return False
    from sylqon.analysis import lane_counter  # lazy: lane_counter imports us
    opp = lane_counter.lane_opponent(ctx)
    if opp is None:
        return False  # blind pick / hidden lane — keep the safe op.gg default
    opp_name = getattr(opp, "name", "")
    # An unkillable lane (tank / heavy sustain) wants map pressure (TP), not a
    # dive summoner.
    return opp_name not in (static.HEAVY_TANK | static.HEAVY_HEALING)


def _enemy_poke_count(ctx: MatchContext) -> int:
    """How many enemies are flagged as poke threats. Tolerant of stub contexts
    (a non-iterable ``enemies`` degrades to 0)."""
    try:
        return sum(
            1 for e in ctx.enemies
            if "poke" in (e.get("threats", []) if isinstance(e, dict)
                          else getattr(e, "threats", []))
        )
    except TypeError:  # pragma: no cover - mocked ctx without a real enemy list
        return 0


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

    # Opener: role starter (jungle pet / support item) + a guaranteed consumable,
    # then the lane-matchup starter swap (poke lane → Doran's Shield etc.).
    from sylqon.analysis import lane_counter  # lazy: lane_counter imports us
    starting = _with_starter_consumable(
        _with_role_starter(build.get("starting_items", []), ctx.my_role))
    starting, starter_reason = lane_counter.matchup_starting_items(starting, ctx)
    opp = lane_counter.lane_opponent(ctx)

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
        first_back=lane_counter.first_back_items(ctx),
        lane_opponent_name=getattr(opp, "name", "") if opp is not None else "",
        starter_reason=starter_reason,
    )


def apply_ai_decision(base: Loadout, ai: dict | None, ctx: MatchContext,
                      catalog: Catalog, candidate: dict | None = None) -> Loadout:
    """Merge the AI's selections onto the candidate build, field by field,
    keeping the deterministic base wherever the AI output is invalid.

    ``candidate`` is the cached/seed build dict ``base`` was compiled from. It is
    optional (everything degrades to ``base``'s own fields when omitted) and lets
    the threat-aware shard logic and counter-item enforcement read the original
    op.gg pool / shards directly.
    """
    out = base
    has_ai = isinstance(ai, dict)
    ai_dict: dict = ai if has_ai else {}
    if not has_ai:
        log.info("No usable AI output; using %s build verbatim", base.source)

    # --- Pool format: core_items + situational_items -------------------------
    has_pool = bool(base.situational_pool and base.core_items and base.boots is not None)

    if has_ai and has_pool and ("core_items" in ai_dict or "situational_items" in ai_dict):
        pool_names = {item["name"] for item in base.situational_pool}
        default_core_names = [item["name"] for item in base.core_items]
        # Expected situational slots: total items minus boots(1) minus core items
        situational_count = len(base.items) - 1 - len(base.core_items)

        # Validate core_items: same count as default, max 1 swap, swapped item in pool
        ai_core = ai.get("core_items", [])
        final_core_names = default_core_names
        if isinstance(ai_core, list) and len(ai_core) == len(base.core_items):
            ai_core_names = [str(n) for n in ai_core]
            swaps = sum(1 for n in ai_core_names if n not in default_core_names)
            swapped_in_pool = all(
                n in pool_names for n in ai_core_names if n not in default_core_names
            )
            all_exist = all(catalog.item_id(n) is not None for n in ai_core_names)
            eligible = all(_item_eligible_for_champion(n, ctx.my_champion)
                           for n in ai_core_names)
            if swaps <= 1 and swapped_in_pool and all_exist and eligible:
                final_core_names = ai_core_names
            else:
                log.debug(
                    "AI core_items rejected (swaps=%d, pool_ok=%s, exist=%s, eligible=%s)",
                    swaps, swapped_in_pool, all_exist, eligible,
                )

        # Validate situational_items: exact count, all from pool, no dups, type-eligible
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
            eligible = all(_item_eligible_for_champion(n, ctx.my_champion)
                           for n in ai_situ_names)
            if no_dup and all_in_pool and all_exist and eligible:
                situ_valid = True
            else:
                log.debug(
                    "AI situational_items rejected (no_dup=%s, pool_ok=%s, exist=%s, eligible=%s)",
                    no_dup, all_in_pool, all_exist, eligible,
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

    from sylqon.ai.prompts import rune_pool_for_champion
    champion_rune_pool = rune_pool_for_champion(ctx.my_champion)

    _apply_runes(out, ai_dict, ctx, rune_pool=champion_rune_pool)
    _apply_shards(out, ai_dict, ctx, candidate)
    _apply_spells(out, ai_dict, ctx)

    # Code-level counter-item guarantee. Runs even without AI so threat coverage
    # holds when Ollama is unavailable; a no-op when no threat mandates a swap.
    enforced = _enforce_counter_items(base, out.items, candidate or {}, ctx, catalog)
    if enforced and len(enforced) == len(out.items):
        out.items = enforced

    if has_ai:
        out.reasoning = str(ai_dict.get("reasoning", ""))[:300]
        out.source = f"{base.source}+ollama"
    return out


def _apply_runes(out: Loadout, ai: dict, ctx: MatchContext,
                 rune_pool: dict | None = None) -> None:
    """Apply the AI's rune block only as a pool-constrained filter over the
    candidate (meta op.gg) page.

    Without a champion pool the legacy permissive behaviour holds (any globally
    valid block is accepted). With a pool we keep the meta keystone + primary
    core unless a strong threat justifies a pool-legal keystone swap, and reject
    any primary rune outside the champion's flexible pool — so the AI can only
    retune the flexible defensive / utility slots. Any rejection falls back to
    the candidate page deterministically."""
    ks = ai.get("keystone", "")
    prim = ai.get("primary_runes", [])
    sec = ai.get("secondary_runes", [])
    sec_style = ai.get("secondary_style", "")
    if not _valid_rune_block(ks, prim, sec, sec_style, rune_pool=rune_pool):
        log.debug("AI rune block rejected; keeping candidate runes")
        return

    if rune_pool is not None:
        # Candidate keystone currently on the loadout = the meta fallback.
        cand_ks = static.RUNE_BY_ID.get(out.rune_perk_ids[0]) if out.rune_perk_ids else None
        if ks != cand_ks and not (
            _strong_threat(_safe_threat(ctx)) and ks in rune_pool["keystone_options"]
        ):
            log.debug("Keystone swap %s->%s not threat-justified; keeping meta page",
                      cand_ks, ks)
            return
        if not all(r in rune_pool["primary_minor_flex"] for r in prim):
            log.debug("AI primary runes outside champion flex pool; keeping meta page")
            return

    out.primary_style_id = static.RUNE_STYLES[static.KEYSTONE_STYLE[ks]]
    out.secondary_style_id = static.RUNE_STYLES[sec_style]
    out.rune_perk_ids = _rune_ids(ks, prim, sec)


def _apply_shards(out: Loadout, ai: dict, ctx: MatchContext,
                  candidate_build: dict | None = None) -> None:
    """Threat-aware, meta-anchored stat shards.

    The op.gg shards are the base; the defense (and, vs decisive AP, the flex)
    row is overridden deterministically from the enemy AD/AP balance and CC load.
    This computed trio is ALWAYS written, so a missing/garbage AI shard output
    still yields a matchup-aware page. A valid AI page may keep its offense/flex
    picks, but its defense pick is only honoured when it is no worse than the
    computed shard for this comp (never undo CC/AP/AD cover)."""
    threat = _safe_threat(ctx)
    base_shards = _base_shard_names(out, candidate_build)
    computed = _compute_default_shards(threat, base_shards)
    final = list(computed)

    shards = ai.get("stat_shards", []) if isinstance(ai, dict) else []
    rows = [static.SHARD_ROW_OFFENSE, static.SHARD_ROW_FLEX, static.SHARD_ROW_DEFENSE]
    if (isinstance(shards, list) and len(shards) == 3
            and all(s in rows[i] for i, s in enumerate(shards))):
        # Offense/flex are only honoured on the op.gg pick or the universally
        # safe Adaptive Force — a within-row but champion-alien pick (e.g.
        # Attack Speed on a burst mage) never overrides the meta page.
        if shards[0] in {base_shards[0], "Adaptive Force"}:
            final[0] = shards[0]
        if shards[1] in {base_shards[1], "Adaptive Force"}:
            final[1] = shards[1]
        if shards[2] in _acceptable_defense_shards(threat):
            final[2] = shards[2]                            # honour a threat-consistent defense

    out.shard_ids = [static.STAT_SHARDS[s] for s in final]


def _apply_spells(out: Loadout, ai: dict, ctx: MatchContext) -> None:
    if ctx.my_role != "jungle" and ai.get("spell1") in out.allowed_spell1:
        if ai["spell1"] != out.spell1:
            log.info("AI changed D-key spell: %s -> %s", out.spell1, ai["spell1"])
        out.spell1 = ai["spell1"]
    if ai.get("spell2") in out.allowed_spell2:
        out.spell2 = ai["spell2"]


def apply_ai_open_decision(base: Loadout, ai: dict | None, ctx: MatchContext,
                           catalog: Catalog, candidate: dict | None = None) -> Loadout:
    """Like apply_ai_decision but for OpenBuild mode.

    Differences from the standard path:
    - has_pool only requires core_items (no situational_pool check).
    - Core swap target only needs to exist in catalog, not in the op.gg pool.
    - Situational items only need to exist in catalog (no pool membership check).
    - Source suffix is +ollama-open.
    """
    out = base
    has_ai = isinstance(ai, dict)
    ai_dict: dict = ai if has_ai else {}
    if not has_ai:
        log.info("No usable AI output; using %s build verbatim", base.source)

    has_pool = bool(base.core_items) and base.boots is not None

    if has_ai and has_pool and ("core_items" in ai_dict or "situational_items" in ai_dict):
        default_core_names = [item["name"] for item in base.core_items]
        situational_count = len(base.items) - 1 - len(base.core_items)

        ai_core = ai.get("core_items", [])
        final_core_names = default_core_names
        if isinstance(ai_core, list) and len(ai_core) == len(base.core_items):
            ai_core_names = [str(n) for n in ai_core]
            swaps = sum(1 for n in ai_core_names if n not in default_core_names)
            all_exist = all(catalog.item_id(n) is not None for n in ai_core_names)
            eligible = all(_item_eligible_for_champion(n, ctx.my_champion)
                           for n in ai_core_names)
            if swaps <= 1 and all_exist and eligible:
                final_core_names = ai_core_names
            else:
                log.debug(
                    "AI core_items rejected (swaps=%d, exist=%s, eligible=%s)",
                    swaps, all_exist, eligible,
                )

        ai_situ = ai.get("situational_items", [])
        situ_valid = False
        if isinstance(ai_situ, list) and len(ai_situ) == situational_count:
            ai_situ_names = [str(n) for n in ai_situ]
            occupied = {base.boots["name"]} | set(final_core_names)
            no_dup = len(set(ai_situ_names)) == situational_count and not (
                set(ai_situ_names) & occupied
            )
            all_exist = all(catalog.item_id(n) is not None for n in ai_situ_names)
            eligible = all(_item_eligible_for_champion(n, ctx.my_champion)
                           for n in ai_situ_names)
            if no_dup and all_exist and eligible:
                situ_valid = True
            else:
                log.debug(
                    "AI situational_items rejected (no_dup=%s, exist=%s, eligible=%s)",
                    no_dup, all_exist, eligible,
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

    from sylqon.ai.prompts import rune_pool_for_champion
    champion_rune_pool = rune_pool_for_champion(ctx.my_champion)

    _apply_runes(out, ai_dict, ctx, rune_pool=champion_rune_pool)
    _apply_shards(out, ai_dict, ctx, candidate)
    _apply_spells(out, ai_dict, ctx)

    # Code-level counter-item guarantee (same as the standard path).
    enforced = _enforce_counter_items(base, out.items, candidate or {}, ctx, catalog)
    if enforced and len(enforced) == len(out.items):
        out.items = enforced

    if has_ai:
        out.reasoning = str(ai_dict.get("reasoning", ""))[:300]
        out.source = f"{base.source}+ollama-open"
    return out
