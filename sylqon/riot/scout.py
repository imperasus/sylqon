"""Riot API-based scouting: rank + match-history fingerprint for any PUUID.

Used for live-game scouting where the LCU match history is unavailable.
SPECTATOR-V5 reveals all 10 PUUIDs, then LEAGUE-V4 + MATCH-V5 + MASTERY-V4 build
the same PlayerFingerprint shape that lobby scouting produces for allies, plus:

  - a richer ``account`` summary (solo + flex rank, season W/L, hot-streak flags),
  - ``detect_premades`` — who is queued together, from shared recent matches,
  - ``current_champ_stats`` — games/WR + mastery on the champ a player is on now.

Match history is fetched across all queues (Normal Draft counts, not just ranked
solo) and filtered to Summoner's Rift here, so players who mostly queue normals
still get a full fingerprint and premade read.
"""
from __future__ import annotations

import concurrent.futures
import logging
from collections import defaultdict

from sylqon import config
from sylqon.lcu.history import SR_QUEUES
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


def _entry_for(entries: list | None, queue_type: str) -> dict | None:
    if not entries:
        return None
    for e in entries:
        if e.get("queueType") == queue_type:
            return e
    return None


def _solo_entry(entries: list | None) -> dict | None:
    return _entry_for(entries, "RANKED_SOLO_5x5")


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


def _pack_rank(entry: dict | None) -> dict | None:
    """Structured ranked-queue summary: tier/division/LP, season W/L + win-rate,
    and the Riot status flags (hot streak, fresh blood, veteran)."""
    if not entry:
        return None
    wins = entry.get("wins", 0) or 0
    losses = entry.get("losses", 0) or 0
    total = wins + losses
    return {
        "tier": entry.get("tier", ""),
        "division": entry.get("rank", ""),
        "lp": entry.get("leaguePoints", 0),
        "wins": wins,
        "losses": losses,
        "games": total,
        "win_rate": round(wins / total, 3) if total else None,
        "hot_streak": bool(entry.get("hotStreak")),
        "fresh_blood": bool(entry.get("freshBlood")),
        "veteran": bool(entry.get("veteran")),
        "label": rank_label(entry),
    }


def account_summary(entries: list | None, mastery: list | None = None) -> dict:
    """Full account read for a player: solo + flex rank, season record + flags,
    and the top mastery pool (pool-shaped). Empty-safe."""
    solo = _solo_entry(entries)
    flex = _entry_for(entries, "RANKED_FLEX_SR")
    return {
        "rank": rank_label(solo),
        "solo": _pack_rank(solo),
        "flex": _pack_rank(flex),
        "mastery": _mastery_pool(mastery),
    }


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


def _team_map(match: dict) -> dict[str, int]:
    """{puuid: teamId} for every participant in a match — the raw signal premade
    detection cross-references across players' histories."""
    info = match.get("info") or {}
    return {
        p.get("puuid"): p.get("teamId")
        for p in info.get("participants") or []
        if p.get("puuid")
    }


def scout_puuid(puuid: str) -> tuple[PlayerFingerprint, dict, dict]:
    """Full scout for one PUUID: ``(fingerprint, account, comatches)``.

    ``comatches`` maps ``gameId -> {puuid: teamId}`` for each recent SR game, so
    ``detect_premades`` can find players who shared a team. Never raises — returns
    empty structures on any failure."""
    if not puuid or not config.RIOT_API_KEY:
        return PlayerFingerprint(), account_summary(None), {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        f_rank    = ex.submit(api.get_ranked_stats, puuid)
        f_mastery = ex.submit(api.get_top_mastery, puuid, 5)
        f_ids     = ex.submit(api.get_match_ids, puuid, config.RIOT_MATCH_COUNT)
        entries   = f_rank.result()
        mastery   = f_mastery.result()
        match_ids = f_ids.result() or []

    games: list[dict] = []
    comatches: dict[str, dict] = {}
    for mid in match_ids:
        raw = api.get_match(mid)
        if not raw:
            continue
        info = raw.get("info") or {}
        if info.get("queueId") not in SR_QUEUES:
            continue   # skip ARAM / bots / events — keep ranked + normal draft
        comatches[str(info.get("gameId") or mid)] = _team_map(raw)
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

    return fp, account_summary(entries, mastery), comatches


def scout_all(puuids: list[str],
              max_workers: int = 5) -> dict[str, tuple[PlayerFingerprint, dict, dict]]:
    """Scout multiple PUUIDs in parallel.
    Returns ``{puuid: (fingerprint, account, comatches)}``."""
    results: dict[str, tuple[PlayerFingerprint, dict, dict]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(scout_puuid, p): p for p in puuids if p}
        for fut in concurrent.futures.as_completed(futures):
            puuid = futures[fut]
            try:
                results[puuid] = fut.result()
            except Exception as exc:
                log.warning("scout_all: puuid %s… failed: %s", puuid[:8], exc)
                results[puuid] = (PlayerFingerprint(), account_summary(None), {})
    return results


def detect_premades(current_puuids, comatches_by_puuid: dict[str, dict],
                    threshold: int = 2) -> list[list[str]]:
    """Find premade groups among the current roster.

    Two players are *linked* when they appear on the **same team** in at least
    ``threshold`` shared recent matches; a premade group is a connected component
    of those links (so a trio links transitively). Matches are de-duplicated by
    id across every player's history. Returns groups of size >= 2 only, each a
    sorted puuid list; solo players are omitted."""
    current = {p for p in current_puuids if p}
    if len(current) < 2:
        return []

    # Merge every player's recent matches, de-duped by game id.
    merged: dict[str, dict] = {}
    for cm in comatches_by_puuid.values():
        for gid, teammap in (cm or {}).items():
            merged.setdefault(gid, teammap)

    # Count same-team co-occurrences within the current roster.
    pair_count: dict[tuple[str, str], int] = defaultdict(int)
    for teammap in merged.values():
        by_team: dict[int, list[str]] = defaultdict(list)
        for pu, team in teammap.items():
            if pu in current:
                by_team[team].append(pu)
        for members in by_team.values():
            members = sorted(set(members))
            for i in range(len(members)):
                for j in range(i + 1, len(members)):
                    pair_count[(members[i], members[j])] += 1

    # Union-find over edges that clear the threshold.
    parent = {p: p for p in current}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for (a, b), n in pair_count.items():
        if n >= threshold:
            union(a, b)

    groups: dict[str, list[str]] = defaultdict(list)
    for p in current:
        groups[find(p)].append(p)
    return sorted(
        (sorted(g) for g in groups.values() if len(g) >= 2),
        key=lambda g: (-len(g), g[0]),
    )


def current_champ_stats(fp: PlayerFingerprint | None, mastery: list | None,
                        champion_id: int) -> dict:
    """Games + win-rate (from the recent pool) and mastery (points + level) for
    the champion a player is currently on. Any missing piece comes back as
    ``None`` so the UI can show what it has (e.g. mastery-only for a first-timer
    in their recent sample, or games-only when the champ is outside top mastery)."""
    out = {"games": None, "win_rate": None,
           "mastery_points": None, "mastery_level": None}
    if not champion_id:
        return out

    pool = (fp.champion_pool if fp else None) or []
    for e in pool:
        if e.get("champion_id") == champion_id:
            out["games"] = e.get("games")
            out["win_rate"] = e.get("win_rate")
            out["mastery_points"] = e.get("mastery_points")
            out["mastery_level"] = e.get("mastery_level")
            break

    if out["mastery_points"] is None:
        for m in mastery or []:
            if m.get("champion_id") == champion_id:
                out["mastery_points"] = m.get("mastery_points")
                out["mastery_level"] = m.get("mastery_level")
                break
    return out
