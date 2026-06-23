"""AI lane game-plan for the locked pick.

Turns the finished matchup (your champion, the enemy comp, your direct lane
opponent) into a short early / mid / late game plan via the shared Ollama
engine. Mirrors the determinism + graceful-fallback contract of the build
engine: returns ``None`` when Ollama is unavailable or the response is unusable,
so the post-lock view falls back to the deterministic scorecard and never
blocks the injection path.
"""
from __future__ import annotations

import logging

from sylqon.lcu.lobby import MatchContext

log = logging.getLogger(__name__)


def _kit_fact_sheet(ctx: MatchContext, matchup: dict | None) -> str:
    """A FACT SHEET of the real, matchup-relevant champion abilities, or ``""``.

    Behind ``SYLQON_RAG_KIT``: grounds the lane plan in actual kits (your champ +
    lane opponent in full, plus the enemy team's key CC/engage by similarity) so
    the model stops inventing cooldowns/effects. Any failure → ``""`` (the plan
    runs ungrounded, exactly as before)."""
    from sylqon import config

    if not config.RAG_KIT_MODE:
        return ""
    try:
        from sylqon.rag import kit_retrieve

        enemies = [e.name for e in ctx.enemies] if ctx.enemies else []
        opp = (matchup or {}).get("lane_opponent") or {}
        focus = [ctx.my_champion]
        if opp.get("name"):
            focus.append(opp["name"])
        facts = kit_retrieve.retrieve_kit_facts(
            champions=focus,
            query=kit_retrieve.build_matchup_query(ctx.my_champion, enemies),
            pool_champions=enemies,
            limit=config.RAG_KIT_LIMIT,
        )
        sheet = kit_retrieve.format_kit_facts(facts)
        return f"\n{sheet}\n" if sheet else ""
    except Exception as exc:  # never break the lane plan over RAG
        log.warning("RAG kit grounding failed (%s); lane plan ungrounded", exc)
        return ""


def _scout_fusion_block(ctx: MatchContext, scout_players: list[dict] | None) -> str:
    """A per-enemy 'how they play' block fusing scout fingerprints with each
    enemy's key ability, or ``""``. Behind ``SYLQON_RAG_FUSION``; needs enemy
    scout data (absent in ranked solo). Any failure → ``""``."""
    from sylqon import config

    if not config.RAG_FUSION_MODE or not scout_players:
        return ""
    try:
        from sylqon.ai import scout_fusion
        from sylqon.rag.item_index import load_index

        kit_index = load_index(config.RAG_KIT_INDEX_PATH)  # None → behavioural only
        block = scout_fusion.fuse_enemy_intel(ctx, scout_players, kit_index=kit_index)
        return f"\n{block}\n" if block else ""
    except Exception as exc:  # never break the lane plan over RAG
        log.warning("RAG scout fusion failed (%s); skipping", exc)
        return ""


class LaneCoach:
    def __init__(self, engine) -> None:
        self.engine = engine

    def plan(self, ctx: MatchContext, matchup: dict | None,
             draft_intel: dict | None = None,
             scout_players: list[dict] | None = None) -> dict | None:
        if not self.engine.available():
            return None
        raw = self.engine.evaluate(
            self._build_prompt(ctx, matchup, draft_intel, scout_players),
            options={"num_predict": 512})
        if not isinstance(raw, dict):
            return None
        clip = lambda key, n=240: str(raw.get(key, "")).strip()[:n]
        early, mid, late = clip("early"), clip("mid"), clip("late")
        if not (early or mid or late):
            return None  # empty payload — no better than the deterministic read
        return {
            "early": early, "mid": mid, "late": late,
            "win_condition": clip("win_condition", 200),
        }

    @staticmethod
    def _build_prompt(ctx: MatchContext, matchup: dict | None,
                      draft_intel: dict | None,
                      scout_players: list[dict] | None = None) -> str:
        opp = (matchup or {}).get("lane_opponent")
        if opp:
            adv = opp.get("advantage")
            edge = ("you are favoured" if adv and adv > 1.5
                    else "they are favoured" if adv and adv < -1.5 else "roughly even")
            opp_line = (f"{opp['name']} ({opp.get('damage_type', '?')} damage; "
                        f"threats: {', '.join(opp.get('threats') or []) or 'none'}; "
                        f"head-to-head: {edge})")
        else:
            opp_line = "unknown / no direct laner revealed"

        enemy_lines = "\n".join(f"- {e.describe()}" for e in ctx.enemies) \
            or "- enemy team hidden"
        ally_lines = "\n".join(f"- {a.describe()}" for a in ctx.allies) \
            or "- no team-mates locked yet"
        comp = (draft_intel or {}).get("enemy_comp") or {}
        comp_line = comp.get("label", "unknown")
        comp_plan = comp.get("counter_plan", "")
        kit_facts = _kit_fact_sheet(ctx, matchup)
        scout_block = _scout_fusion_block(ctx, scout_players)

        return f"""You are a League of Legends laning coach. The player has LOCKED IN their champion. Give a concise, concrete game plan for THIS specific matchup. Be specific to these champions — reference abilities, item/level spikes and timings where it helps; no generic filler.

MY CHAMPION: {ctx.my_champion}, role {ctx.my_role}
DIRECT LANE OPPONENT: {opp_line}

MY TEAM:
{ally_lines}

ENEMY TEAM:
{enemy_lines}
{kit_facts}{scout_block}
ENEMY COMPOSITION: {comp_line}
HOW TO BEAT IT: {comp_plan}

TASK: Write a 3-phase plan plus the single win condition. Each phase is exactly ONE sentence.
- early: levels 1-6, the laning phase — wave management, the trading pattern, all-in windows, what to respect.
- mid: levels 7-13 — grouping, objectives, your power spikes vs theirs.
- late: level 14+ — teamfight positioning and the mistake to avoid.
- win_condition: the one thing that wins this game.

Respond with raw JSON only, exactly this shape:
{{"early": "...", "mid": "...", "late": "...", "win_condition": "..."}}"""
