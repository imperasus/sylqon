"""Deterministic matchup-aware core-combo selection.

Picks, from the real op.gg core combos carried on the candidate build
(``core_options``), the combo that best covers the counter tags the enemy comp
mandates. Pure code, no LLM: it runs as a pre-step before
``loadout.from_candidate``, so the standard pipeline, OpenBuild, the AI's
1-swap budget, and counter enforcement all operate on a matchup-correct core.

The meta default only loses to a challenger that
- covers strictly MORE mandated counter tags (urgent tags weigh double),
- clears the sample floor (absolute games AND share of combo games),
- is type-legal for the champion, and
- does not win-rate-tank versus the meta combo.

A balanced enemy comp mandates nothing, so it always keeps the meta combo —
deviation happens exactly when the draft justifies it.
"""
from __future__ import annotations

import logging

from sylqon.analysis.lane_counter import combined_requirements
from sylqon.data import static
from sylqon.lcu.lobby import MatchContext
from sylqon.loadout import _item_eligible_for_champion

log = logging.getLogger(__name__)

# Sample floor for a challenger combo, adaptive to the data source's scale:
# op.gg pages carry thousands of games (floor caps at MIN_COMBO_GAMES), the
# hosted Sylqon service aggregates a few dozen (floor relaxes toward
# MIN_COMBO_GAMES_FLOOR) — floor = max(FLOOR, min(CAP, 10% of total games)).
MIN_COMBO_GAMES = 20
MIN_COMBO_GAMES_FLOOR = 8
MIN_COMBO_SHARE = 0.03   # ...and at least this share of all combo games
WIN_RATE_SLACK = 0.05    # challenger may not be >5pp worse than the meta combo
URGENT_WEIGHT = 2        # urgent counter tags (anti-heal/%pen/anti-CC/anti-burst)
SOFT_WEIGHT = 1          # defensive preferences (armor/mr)

# Human label for the reason string, keyed by the first newly covered tag.
_TAG_LABELS = {
    "anti_heal": "Anti-heal",
    "percent_pen": "Anti-tank",
    "tank_shred": "Anti-tank",
    "anti_cc": "Anti-CC",
    "anti_burst": "Survival",
    "armor": "Armor",
    "mr": "Magic-resist",
}


def _tags_of(item: dict) -> set[str]:
    return set(static.ITEM_COUNTER_TAGS.get(item.get("id") or 0, ()))


def _coverage(items: list[dict], reqs: list[tuple[set[str], bool]]) -> int:
    """Weighted count of requirement sets this item list covers."""
    score = 0
    for accepted, urgent in reqs:
        if any(_tags_of(it) & accepted for it in items):
            score += URGENT_WEIGHT if urgent else SOFT_WEIGHT
    return score


def _covered_tags(items: list[dict]) -> set[str]:
    out: set[str] = set()
    for it in items:
        out |= _tags_of(it)
    return out


def select_core(candidate: dict, ctx: MatchContext) -> tuple[dict | None, str]:
    """The core combo to use against this enemy comp.

    Returns ``(combo, reason)`` when a challenger from ``core_options`` beats
    the default core, else ``(None, "")`` — keep the meta combo. Never raises;
    any structural surprise degrades to "keep meta"."""
    options = candidate.get("core_options") or []
    default_core = candidate.get("core_items") or []
    if len(options) < 2 or len(default_core) != 3:
        return None, ""

    # Lane + team mandates, lane first — a core combo that answers the direct
    # lane opponent outweighs one that only answers the aggregate comp.
    reqs = combined_requirements(ctx)
    if not reqs:
        return None, ""  # balanced comp: nothing mandated, meta stays

    default_ids = {it.get("id") for it in default_core}
    baseline = _coverage(default_core, reqs)

    total_games = sum(o.get("games") or 0 for o in options)
    min_games = max(MIN_COMBO_GAMES_FLOOR,
                    min(MIN_COMBO_GAMES, int(total_games * 0.10)))
    meta_wr = next(
        (o.get("win_rate") for o in options
         if {it.get("id") for it in o.get("items", [])} == default_ids),
        None,
    )

    champion = getattr(ctx, "my_champion", "") or ""
    best: dict | None = None
    best_score = baseline
    for opt in options:
        items = opt.get("items") or []
        if len(items) != 3 or {it.get("id") for it in items} == default_ids:
            continue
        games = opt.get("games") or 0
        if games < min_games:
            continue
        if total_games and games / total_games < MIN_COMBO_SHARE:
            continue
        if not all(_item_eligible_for_champion(it.get("name", ""), champion)
                   for it in items):
            continue
        wr = opt.get("win_rate") or 0.0
        if meta_wr is not None and wr < meta_wr - WIN_RATE_SLACK:
            continue
        score = _coverage(items, reqs)
        # Strictly-better rule: ties (and worse) keep the meta combo. Among
        # equal challengers the bigger sample wins (options are play-ranked,
        # so the first best seen has the most games).
        if score > best_score:
            best, best_score = opt, score

    if best is None:
        return None, ""

    gained = _covered_tags(best["items"]) - _covered_tags(default_core)
    mandated = set().union(*(accepted for accepted, _ in reqs))
    key_tags = [t for t in ("anti_heal", "percent_pen", "tank_shred", "anti_cc",
                            "anti_burst", "armor", "mr")
                if t in (gained & mandated)]
    label = _TAG_LABELS.get(key_tags[0], "Counter") if key_tags else "Counter"
    swapped_in = [it["name"] for it in best["items"]
                  if it.get("id") not in default_ids]
    reason = (
        f"{label} core: {', '.join(swapped_in) or 'alternative combo'} covers "
        f"{'/'.join(key_tags) or 'the mandated threats'} the meta core lacks "
        f"(op.gg: {best.get('games', 0)} games, "
        f"{round((best.get('win_rate') or 0.0) * 100, 1)}% WR)"
    )
    return best, reason


def apply_core_selection(candidate: dict, ctx: MatchContext, catalog) -> dict:
    """Candidate build with the matchup-selected core folded in.

    Returns the candidate unchanged (same object) when the meta combo stays.
    Otherwise returns a copy whose ``core_items``/``items``/``situational_pool``
    reflect the chosen combo: displaced default-core items join the pool (they
    are meta-proven picks the AI and counter enforcement should still reach),
    and ``core_reason`` records why — surfaced in the UI and the prompts."""
    boots = candidate.get("boots")
    if not boots or not candidate.get("situational_pool"):
        return candidate  # legacy flat build: no boots+core+pool structure

    combo, reason = select_core(candidate, ctx)
    if combo is None:
        return candidate

    old_core = candidate.get("core_items", [])
    situ_count = len(candidate.get("items", [])) - 1 - len(old_core)
    if situ_count < 1:
        return candidate

    new_core = [{"id": it["id"], "name": it["name"]} for it in combo["items"]]
    new_ids = {it["id"] for it in new_core}

    pool = [dict(p) for p in candidate["situational_pool"]
            if p.get("id") not in new_ids]
    pool_ids = {p.get("id") for p in pool}
    for it in old_core:
        if it["id"] in new_ids or it["id"] in pool_ids or it["id"] == boots.get("id"):
            continue
        entry = {"id": it["id"], "name": it["name"]}
        desc = catalog.item_description(it["name"]) if catalog is not None else ""
        if desc:
            entry["description"] = desc
        pool.append(entry)
        pool_ids.add(it["id"])

    if len(pool) < situ_count:
        # The swap would leave too few situational picks to fill the item set —
        # keep the meta build rather than emit a short loadout.
        log.debug("Core selection skipped: pool too thin after swap (%d < %d)",
                  len(pool), situ_count)
        return candidate

    out = dict(candidate)
    out["core_items"] = new_core
    out["situational_pool"] = pool
    out["items"] = (
        [{"id": boots["id"], "name": boots["name"]}]
        + new_core
        + [{"id": p["id"], "name": p["name"]} for p in pool[:situ_count]]
    )
    out["core_reason"] = reason
    log.info("Matchup core selected for %s %s: %s",
             ctx.my_champion, ctx.my_role, reason)
    return out
