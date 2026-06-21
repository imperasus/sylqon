"""Riot API-based scouting: rank + match-history fingerprint for any PUUID.

Used for live-game enemy scouting where the LCU match history is unavailable.
SPECTATOR-V5 reveals all 10 PUUIDs, then LEAGUE-V4 + MATCH-V5 build the same
PlayerFingerprint shape that lobby scouting produces for allies.
"""
from __future__ import annotations

import concurrent.futures
import logging

from sylqon import config
from sylqon.lcu.scout import PlayerFingerprint, fingerprint
from sylqon.riot import api

log = logging.getLogger(__name__)

_TIER_SHORT = {
    "IRON": "I", "BRONZE": "B", "SILVER": "S", "GOLD": "G",
    "PLATINUM": "P", "EMERALD": "E", "DIAMOND": "D",
    "MASTER": "M", "GRANDMASTER": "GM", "CHALLENGER": "C",
}
_DIVISION = {"I": 1, "II": 2, "III": 3, "IV": 4}

_ROLE_MAP = {
    "top": "top", "jungle": "jungle", "mid": "middle", "middle": "middle",
    "bottom": "bottom", "adc": "bottom", "utility": "utility", "support": "utility",
}


def _solo_entry(entries: list | None) -> dict | None:
    if not entries:
        return None
    for e in entries:
        if e.get("queueType") == "RANKED_SOLO_5x5":
            return e
    return None


def rank_label(entry: dict | None) -> str:
    """'G2 · 67 LP' style label, or '' if unranked."""
    if not entry:
        return ""
    tier = entry.get("tier", "")
    div = entry.get("rank", "")
    lp = entry.get("leaguePoints", 0)
    t = _TIER_SHORT.get(tier, tier[:1])
    d = _DIVISION.get(div, "")
    return f"{t}{d} · {lp} LP"


def _normalize_match_for_fingerprint(match: dict, puuid: str) -> dict | None:
    """Convert a MATCH-V5 object into the shape fingerprint() expects."""
    info = match.get("info") or {}
    participants = info.get("participants") or []
    me = next((p for p in participants if p.get("puuid") == puuid), None)
    if not me:
        return None

    duration_s = info.get("gameDuration", 0) or 0
    # Pre-7.20 games store duration in milliseconds.
    if duration_s > 100_000:
        duration_s = duration_s // 1000
    minutes = duration_s / 60.0 if duration_s > 0 else 1.0

    cs = (me.get("totalMinionsKilled") or 0) + (me.get("neutralMinionsKilled") or 0)
    pos = (me.get("teamPosition") or me.get("individualPosition") or "").lower()

    return {
        "champion_id": me.get("championId", 0),
        "role": _ROLE_MAP.get(pos, pos),
        "result": "Win" if me.get("win") else "Loss",
        "gameCreation": info.get("gameCreation", 0),
        "kda": {
            "kills": me.get("kills", 0),
            "deaths": me.get("deaths", 0),
            "assists": me.get("assists", 0),
        },
        "stats": {
            "cs_per_min": round(cs / minutes, 2),
            "duration": duration_s,
            "damage_taken": me.get("totalDamageTaken", 0),
            "vision_score": me.get("visionScore", 0),
        },
    }


def scout_puuid(puuid: str) -> tuple[PlayerFingerprint, str]:
    """Full scout for one PUUID: (fingerprint, rank_label).
    Never raises — returns an empty fingerprint on any failure."""
    if not puuid or not config.RIOT_API_KEY:
        return PlayerFingerprint(), ""

    entries = api.get_ranked_stats(puuid)
    solo = _solo_entry(entries)
    rl = rank_label(solo)

    match_ids = api.get_match_ids(puuid, count=config.RIOT_MATCH_COUNT)
    if not match_ids:
        return PlayerFingerprint(), rl

    games: list[dict] = []
    for mid in match_ids:
        raw = api.get_match(mid)
        if raw:
            norm = _normalize_match_for_fingerprint(raw, puuid)
            if norm:
                games.append(norm)

    fp = fingerprint(games)
    return fp, rl


def scout_all(puuids: list[str],
              max_workers: int = 5) -> dict[str, tuple[PlayerFingerprint, str]]:
    """Scout multiple PUUIDs in parallel. Returns {puuid: (fingerprint, rank_label)}."""
    results: dict[str, tuple[PlayerFingerprint, str]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(scout_puuid, p): p for p in puuids if p}
        for fut in concurrent.futures.as_completed(futures):
            puuid = futures[fut]
            try:
                results[puuid] = fut.result()
            except Exception as exc:
                log.warning("scout_all: puuid %s… failed: %s", puuid[:8], exc)
                results[puuid] = (PlayerFingerprint(), "")
    return results
