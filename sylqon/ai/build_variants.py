"""AI build-variant generation (v2).

Produces up to N *distinct* build variants against the locked enemy comp, using
the op.gg cached build as the baseline. Variant 1 is the primary (the same
validated loadout the pipeline auto-injects); additional variants are alternative
itemisations/runes that are only kept when they meaningfully differ.

Safety: every variant is validated through the existing
``loadout.apply_ai_decision`` — the AI can only swap within the op.gg situational
pool and the static rune tables; anything invalid falls back to the baseline. We
never trust raw AI item/rune names here.
"""
from __future__ import annotations

import logging

from sylqon import loadout as loadout_mod
from sylqon.data import static
from sylqon.data.catalog import Catalog
from sylqon.lcu.lobby import MatchContext

log = logging.getLogger(__name__)


def _signature(l: loadout_mod.Loadout) -> tuple:
    """Identity for dedup: item ids + runes + shards + spells."""
    return (
        tuple(i.get("id") for i in l.items),
        tuple(l.rune_perk_ids),
        tuple(l.shard_ids),
        l.spell1, l.spell2,
    )


def compile_variant_prompt(ctx: MatchContext, candidate: dict, max_variants: int) -> str:
    """Prompt Ollama for up to ``max_variants`` distinct variants as deltas over
    the op.gg baseline. The response is validated downstream, so the prompt only
    needs to steer usefulness, not legality."""
    boots = (candidate.get("boots") or {}).get("name", "Boots")
    core = ", ".join(i["name"] for i in candidate.get("core_items", [])) or "—"
    if candidate.get("core_reason"):
        core += f"\n    (matchup-selected core — {candidate['core_reason']})"
    # Real alternative core combos (op.gg data). A variant can anchor to one
    # that differs by a single item via its ONE allowed core swap — the swapped
    # item is guaranteed present in the situational pool by the converter.
    core_names = [i["name"] for i in candidate.get("core_items", [])]
    alt_combos = "\n".join(
        f"  - {', '.join(i['name'] for i in o.get('items', []))} "
        f"— {o.get('games', 0)} games, {round((o.get('win_rate') or 0) * 100, 1)}% WR"
        for o in candidate.get("core_options") or []
        if sorted(i["name"] for i in o.get("items", [])) != sorted(core_names)
    )
    pool = "\n".join(
        f"  - {it['name']}: {it.get('description', '')}".rstrip()
        for it in candidate.get("situational_pool", [])
    ) or "  (none)"
    enemies = "\n".join(
        f"  - {e.name} ({e.role}, {e.damage_type}): {', '.join(e.threats) or 'no flagged threats'}"
        for e in ctx.enemies
    ) or "  (enemy team hidden)"
    threats = ctx.team_threat_summary()
    situational_count = len(candidate.get("items", [])) - 1 - len(candidate.get("core_items", []))

    return f"""You are a League of Legends draft coach. Champion: {ctx.my_champion} ({ctx.my_role}).

ENEMY TEAM:
{enemies}

ENEMY THREAT SUMMARY (counts): {threats}

OP.GG BASELINE BUILD:
  Boots: {boots}
  Core (keep count = {len(candidate.get('core_items', []))}): {core}
  Situational pool (choose {situational_count} per variant, in order):
{pool}
{f'''
REAL ALTERNATIVE CORE COMBOS (op.gg-proven; a variant may anchor to one that
differs from the baseline core by a single item, using its ONE core swap):
{alt_combos}
''' if alt_combos else ''}
TASK: Produce up to {max_variants} DISTINCT build variants optimised against this enemy team.
RULES:
1. Variant 1 must be the single BEST build vs this comp.
2. Only add variant 2/3 when the enemy has DISTINCT threats needing different items
   (e.g. anti-tank vs %-pen, anti-burst survivability, anti-heal). Quality over quantity.
3. core_items: exactly {len(candidate.get('core_items', []))} names, at most ONE swapped from the situational pool.
4. situational_items: exactly {situational_count} names, all from the situational pool above.
5. Runes are optional to change; if you change them use a keystone EXACTLY from this
   list: {list(static.KEYSTONES)} — plus minor runes from that keystone's own tree.
6. Each variant needs a short "name" (e.g. "Anti-Tank") and 1-sentence "reasoning".

OUTPUT JSON ONLY:
{{"variants": [
  {{"name": "...", "reasoning": "...",
    "core_items": ["..."], "situational_items": ["..."],
    "keystone": "...", "primary_runes": ["...","...","..."],
    "secondary_style": "...", "secondary_runes": ["...","..."],
    "stat_shards": ["...","...","..."],
    "spell1": "...", "spell2": "..."}}
]}}"""


def generate_variants(ctx: MatchContext, candidate: dict, catalog: Catalog,
                      engine, primary: loadout_mod.Loadout,
                      max_variants: int = 3) -> list[loadout_mod.Loadout]:
    """Return [primary, *alternatives], each a validated Loadout, deduped.

    ``primary`` is the already-validated auto-injected loadout (variant 1). If
    Ollama is unavailable or yields nothing distinct, only [primary] is returned.
    """
    primary.name = primary.name or "Recommended"
    out = [primary]
    seen = {_signature(primary)}

    if not ctx.enemies or not engine.available():
        return out

    # Up to 3 full variants (items + runes + shards + spells + reasoning) far
    # exceeds the default 512-token budget, so the JSON would truncate. Give this
    # call plenty of room; it runs off the injection critical path.
    raw = engine.evaluate(compile_variant_prompt(ctx, candidate, max_variants),
                          options={"num_predict": 2048})
    if not isinstance(raw, dict):
        return out

    for v in raw.get("variants") or []:
        if len(out) >= max_variants:
            break
        if not isinstance(v, dict):
            continue
        base = loadout_mod.from_candidate(candidate, ctx, "opgg")
        variant = loadout_mod.apply_ai_decision(base, v, ctx, catalog, candidate)
        sig = _signature(variant)
        if sig in seen:
            continue  # AI produced nothing meaningfully different; drop it
        seen.add(sig)
        variant.name = (str(v.get("name") or "Alternative").strip())[:40] or "Alternative"
        out.append(variant)

    log.info("Generated %d build variant(s) for %s %s",
             len(out), ctx.my_champion, ctx.my_role)
    return out
