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


def _mastery_comfort(mastery: list | None) -> dict | None:
    """Build a comfort dict from the top mastery entry."""
    if not mastery or not isinstance(mastery, list):
        return None
    top = mastery[0]
    return {
        "champion_id": top.get("championId", 0),
        "mastery_points": top.get("championPoints", 0),
        "mastery_level": top.get("championLevel", 0),
        "games": None,
        "win_rate": None,
        "share": None,
    }


def _mastery_pool(mastery: list | None) -> list[dict]:
    """Top mastery champions as a pool list (no games/WR — mastery only)."""
    if not mastery:
        return []
    return [
        {
            "champion_id": m.get("championId", 0),
            "mastery_points": m.get("championPoints", 0),
            "mastery_level": m.get("championLevel", 0),
            "games": None,
            "win_rate": None,
        }
        for m in mastery
    ]


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

    import concurrent.futures as _cf
    with _cf.ThreadPoolExecutor(max_workers=3) as ex:
        f_rank    = ex.submit(api.get_ranked_stats, puuid)
        f_mastery = ex.submit(api.get_top_mastery, puuid, 5)
        f_ids     = ex.submit(api.get_match_ids, puuid, config.RIOT_MATCH_COUNT)
        entries   = f_rank.result()
        mastery   = f_mastery.result()
        match_ids = f_ids.result() or []

    solo = _solo_entry(entries)
    rl = rank_label(solo)

    games: list[dict] = []
    for mid in match_ids:
        raw = api.get_match(mid)
        if raw:
            norm = _normalize_match_for_fingerprint(raw, puuid)
            if norm:
                games.append(norm)

    fp = fingerprint(games)

    if mastery:
        mastery_c = _mastery_comfort(mastery)
        mastery_p = _mastery_pool(mastery)

        if mastery_c:
            history_comfort = fp.comfort or {}
            if (history_comfort.get("champion_id") == mastery_c["champion_id"]
                    and history_comfort.get("win_rate") is not None):
                mastery_c["win_rate"] = history_comfort["win_rate"]
                mastery_c["games"]    = history_comfort["games"]
                mastery_c["share"]    = history_comfort["share"]
            fp.comfort = mastery_c

        history_ids = {e["champion_id"] for e in fp.champion_pool}
        for m in mastery_p:
            if m["champion_id"] not in history_ids:
                fp.champion_pool.append(m)
        fp.champion_pool.sort(
            key=lambda e: (e.get("games") is None, -(e.get("games") or 0))
        )
        fp.champion_pool = fp.champion_pool[:5]

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
