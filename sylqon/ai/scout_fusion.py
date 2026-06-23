"""Scout + kit fusion for the lane plan (RAG roadmap #3).

Joins each scouted ENEMY's behavioural fingerprint (playstyle tags, comfort
pick, recent form, current-champ stats, premade) WITH their champion's key
ability (retrieved from the kit index) into a per-enemy block, so the lane plan
can advise on HOW the opponent tends to play — not just the matchup on paper.

Enemy fingerprints come from the scout state's ``side == "enemy"`` entries
(populated in-game / in normal draft; absent in ranked solo where enemies are
anonymised). Degrades gracefully: behavioural-only when the kit index is missing;
``""`` when there are no enemy fingerprints. Never raises out of the helpers.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def _enemy_scout_players(scout_players: list[dict] | None) -> list[dict]:
    return [
        p for p in (scout_players or [])
        if p.get("side") == "enemy" and not p.get("hidden")
        and p.get("games_analyzed", 0) > 0
    ]


def _behaviour_summary(p: dict) -> str:
    """Compact behavioural read of one scouted player. Pure/testable."""
    bits: list[str] = []
    tags = p.get("playstyle_tags") or []
    if tags:
        bits.append("plays " + ", ".join(tags))
    comfort = p.get("comfort") or {}
    if comfort.get("champion"):
        bits.append(f"mains {comfort['champion']} "
                    f"({round(comfort.get('share', 0) * 100)}% of games)")
    form = p.get("recent_form") or {}
    if form.get("games"):
        streak = form.get("streak", 0)
        run = (f", {abs(streak)}{'W' if streak > 0 else 'L'} streak"
               if abs(streak) >= 3 else "")
        bits.append(f"{round(form.get('win_rate', 0) * 100)}% over last "
                    f"{form['games']}{run}")
    cc = p.get("current_champ") or {}
    if cc.get("games"):
        bits.append(f"{cc['games']} games on this champ "
                    f"({round(cc.get('win_rate', 0) * 100)}% WR)")
    if p.get("premade_partners"):
        bits.append(f"premade ({len(p['premade_partners']) + 1}-stack)")
    return "; ".join(bits)


def _champion_for(p: dict, by_id: dict) -> tuple[str, str]:
    """Resolve (champion_name, role) for a scout entry, joining to ctx.enemies by
    champion_id, with the player's own comfort/position as fallback."""
    pick = by_id.get(p.get("champion_id"))
    if pick is not None:
        return pick.name, (pick.role or p.get("position") or p.get("main_role") or "")
    name = (p.get("comfort") or {}).get("champion", "")
    return name, (p.get("position") or p.get("main_role") or "")


def fuse_enemy_intel(ctx, scout_players: list[dict] | None, *,
                     kit_index: dict | None = None, embedder=None) -> str:
    """Per-enemy fused block (behaviour + key ability), or ``""``.

    ``kit_index`` is optional: when present, each line gets the enemy champion's
    most matchup-relevant ability appended; when ``None``, lines are
    behavioural-only."""
    enemies = _enemy_scout_players(scout_players)
    if not enemies:
        return ""

    by_id = {e.champion_id: e for e in (ctx.enemies or [])}

    kit_retrieve = None
    if kit_index is not None:
        try:
            from sylqon.rag import kit_retrieve as _kr
            kit_retrieve = _kr
            if embedder is None:
                from sylqon.rag.embed import OllamaEmbedder
                embedder = OllamaEmbedder(kit_index.get("model"))
        except Exception:  # pragma: no cover - import guard
            kit_retrieve = None

    lines: list[str] = []
    for p in enemies:
        champ_name, role = _champion_for(p, by_id)
        behaviour = _behaviour_summary(p)
        if not champ_name and not behaviour:
            continue
        head = f"{role + ' ' if role else ''}{champ_name or 'enemy'}".strip()
        line = f"- {head}: {behaviour}" if behaviour else f"- {head}"

        if champ_name and kit_retrieve is not None:
            try:
                facts = kit_retrieve.retrieve_kit_facts(
                    query=kit_retrieve.build_matchup_query(ctx.my_champion, [champ_name]),
                    pool_champions=[champ_name], limit=3,
                    index=kit_index, embedder=embedder)
                if facts:
                    # Prefer an active (Q/W/E/R) — the passive is rarely the
                    # actionable "watch out" ability for a laning pointer.
                    f = next((x for x in facts if x.get("slot") != "Passive"), facts[0])
                    line += f" — watch {champ_name}'s {f['slot']} ({f['ability']})"
            except Exception:
                log.debug("kit lookup failed for %s", champ_name, exc_info=True)
        lines.append(line)

    if not lines:
        return ""
    return ("SCOUTED ENEMY PLAYERS (how these opponents tend to play — factor "
            "their tendencies and their key ability into the plan):\n"
            + "\n".join(lines))
