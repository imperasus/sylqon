"""Local summoner's ranked stats from the LCU.

The Riot-key scout only fetches rank when SPECTATOR-V5 returns the active game,
which it does NOT for custom / practice-tool / bot games — so the local player
would otherwise show "Unranked" there even when they are ranked. The LCU exposes
the current summoner's own ranked stats directly (no Riot key, no rate limit), so
we use it to fill in the player's own rank. READ-ONLY: GET only.
"""
from __future__ import annotations

import logging

from sylqon.lcu.client import LCUClient
from sylqon.riot.scout import rank_label

log = logging.getLogger(__name__)

_UNRANKED_TIERS = {"", "NONE", "UNRANKED"}


def _pack(entry: dict | None) -> dict | None:
    """One LCU queueMap entry → the same shape riot.scout produces, or None when
    the queue is unranked."""
    if not entry:
        return None
    tier = (entry.get("tier") or "").upper()
    if tier in _UNRANKED_TIERS:
        return None
    # LCU calls the division "division"; normalize "NA"/"NONE" to blank (apex tiers).
    division = (entry.get("division") or entry.get("rank") or "").upper()
    if division in ("NA", "NONE"):
        division = ""
    lp = entry.get("leaguePoints", 0) or 0
    wins = entry.get("wins", 0) or 0
    losses = entry.get("losses", 0) or 0
    total = wins + losses
    return {
        "tier": tier,
        "division": division,
        "lp": lp,
        "wins": wins,
        "losses": losses,
        "games": total,
        "win_rate": round(wins / total, 3) if total else None,
        "hot_streak": bool(entry.get("isHotStreak") or entry.get("hotStreak")),
        "fresh_blood": bool(entry.get("isFreshBlood")),
        "veteran": bool(entry.get("isVeteran")),
        "label": rank_label({"tier": tier, "rank": division, "leaguePoints": lp}),
    }


def current_ranked_summary(client: LCUClient) -> dict | None:
    """``{rank, solo, flex, mastery}`` for the local summoner (mirrors
    ``riot.scout.account_summary``), or None on failure / fully unranked."""
    try:
        data = client.get_json("/lol-ranked/v1/current-ranked-stats")
    except Exception:
        log.debug("current-ranked-stats fetch failed", exc_info=True)
        return None
    if not isinstance(data, dict):
        return None
    qm = data.get("queueMap") or {}
    solo = _pack(qm.get("RANKED_SOLO_5x5"))
    flex = _pack(qm.get("RANKED_FLEX_SR"))
    if not solo and not flex:
        return None
    return {
        "rank": (solo or {}).get("label", ""),
        "solo": solo,
        "flex": flex,
        "mastery": [],
    }
