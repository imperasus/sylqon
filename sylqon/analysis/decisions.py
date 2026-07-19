"""Coach layer: the structured "why" behind every deviation from the meta build.

``build_decisions`` diffs the final, matchup-adapted loadout against the
untouched meta baseline (``last_standard``) and emits a human-readable list of
what changed and why — reusing the reasons the deterministic selectors already
recorded (``core_reason`` / ``rune_reason`` / ``starter_reason``) and computing
the rest (boots, shards, spells, enforced counter items, first-back) from the
diff. When nothing deviated, it emits a single "meta is optimal here" entry, so
the player always gets a verdict rather than a blank panel.

Pure and deterministic (no LLM, no DB). The output feeds the post-lock coach
panel, the delta badges, the overlay, and the decision telemetry.
"""
from __future__ import annotations

from sylqon.data import static
from sylqon.lcu.lobby import MatchContext


def _names(items: list[dict]) -> list[str]:
    return [i.get("name", "") for i in items]


def _shard_names(shard_ids: list[int]) -> list[str]:
    return [static.SHARD_BY_ID.get(s, str(s)) for s in shard_ids]


def _keystone_of(rune_perk_ids: list[int]) -> str:
    return static.RUNE_BY_ID.get(rune_perk_ids[0], "") if rune_perk_ids else ""


def _decision(slot: str, summary: str, reason: str, kind: str = "swap") -> dict:
    return {"slot": slot, "summary": summary, "reason": reason, "kind": kind}


def build_decisions(final, meta, candidate: dict, ctx: MatchContext) -> list[dict]:
    """Structured why-list of every deviation of ``final`` from the ``meta``
    baseline. ``candidate`` is the post-selection build dict (carries the
    selector reasons). Never raises — best-effort per slot."""
    out: list[dict] = []

    # --- Core combo (matchup core selector) ---------------------------------
    if candidate.get("core_reason"):
        out.append(_decision(
            "Core", "Matchup core swap", candidate["core_reason"]))

    # --- Rune page (matchup rune selector) ----------------------------------
    if candidate.get("rune_reason"):
        out.append(_decision(
            "Runes", "Matchup rune page", candidate["rune_reason"]))
    elif _keystone_of(final.rune_perk_ids) != _keystone_of(meta.rune_perk_ids):
        out.append(_decision(
            "Runes", f"Keystone → {_keystone_of(final.rune_perk_ids)}",
            "AI retuned the rune page within the champion's pool for this matchup."))

    # --- Boots (matchup defensive tread) ------------------------------------
    fb_boots = final.boots or {}
    mb_boots = meta.boots or {}
    if fb_boots.get("id") and fb_boots.get("id") != mb_boots.get("id"):
        out.append(_decision(
            "Boots", f"{fb_boots.get('name')} over {mb_boots.get('name')}",
            f"Defensive treads chosen over the meta boot for this enemy damage "
            f"profile."))

    # --- Starting items (matchup starter) -----------------------------------
    if final.starter_reason:
        out.append(_decision(
            "Starter", "Lane-adjusted start", final.starter_reason))

    # --- First back (lane counter components) -------------------------------
    if final.first_back:
        opp = final.lane_opponent_name or "your lane opponent"
        out.append(_decision(
            "First Back",
            "Buy first: " + ", ".join(_names(final.first_back)),
            f"Cheap counter components that answer {opp} on the first recall.",
            kind="add"))

    # --- Enforced / reordered counter items ---------------------------------
    meta_ids = [i.get("id") for i in meta.items]
    final_ids = [i.get("id") for i in final.items]
    if final_ids != meta_ids:
        added = [i for i in final.items
                 if i.get("id") not in meta_ids
                 and static.ITEM_COUNTER_TAGS.get(i.get("id", 0))]
        if added:
            labels = []
            for it in added:
                tags = static.ITEM_COUNTER_TAGS.get(it.get("id", 0), ())
                label = static.COUNTER_TAG_INFO.get(tags[0], (tags[0] if tags else "",))[0] \
                    if tags else ""
                labels.append(f"{it.get('name')} ({label})" if label else it.get("name"))
            out.append(_decision(
                "Items", "Counter items enforced: " + ", ".join(labels),
                "The enemy comp mandates these; they replaced greedier picks and "
                "were ordered by spike timing.", kind="add"))

    # --- Summoner spells ----------------------------------------------------
    if final.spell1 != meta.spell1 and ctx.my_role != "jungle":
        out.append(_decision(
            "Spell", f"D-key → {final.spell1} (was {meta.spell1})",
            _spell_reason(final.spell1, ctx)))

    # --- Stat shards --------------------------------------------------------
    fs, ms = _shard_names(final.shard_ids), _shard_names(meta.shard_ids)
    if fs != ms:
        out.append(_decision(
            "Shards", f"Defense shard → {fs[2] if len(fs) == 3 else '?'}",
            "Stat shards adapted to the enemy AD/AP balance and CC load.",
            kind="tune"))

    # --- AI reasoning (freeform tactical note) ------------------------------
    if getattr(final, "reasoning", ""):
        out.append(_decision(
            "Note", "AI tactical note", final.reasoning, kind="note"))

    if not out:
        out.append(_decision(
            "Meta", "Meta build is optimal here",
            "The enemy draft mandates no counter deviation — the meta build for "
            "this champion is the correct pick. Play your standard game plan.",
            kind="keep"))
    return out


def _spell_reason(spell1: str, ctx: MatchContext) -> str:
    reasons = {
        "Cleanse": "Cleanse taken into chain CC (3+ hard-CC enemies) to break the combo.",
        "Barrier": "Barrier taken to survive the enemy burst/poke window.",
        "Exhaust": "Exhaust taken to shut down the enemy's primary carry.",
        "Ignite": "Ignite taken for lane kill pressure into a winnable matchup.",
    }
    return reasons.get(spell1, "Summoner adjusted for the matchup.")
