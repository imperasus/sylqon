"""Per-champion performance from the local match history.

The LCU exposes the current summoner's recent games at
``/lol-match-history/v1/products/lol/current-summoner/matches``. Each game lists
the summoner as ``participants[0]`` with a ``championId`` and ``stats.win``, so
we can aggregate a quick win-rate + games-played figure per champion without any
external API key. Everything degrades to an empty dict on failure — the
dashboard simply omits the overlay.
"""
from __future__ import annotations

import logging

from sylqon.lcu.client import LCUClient

log = logging.getLogger(__name__)

# Summoner's Rift queues worth counting (ranked solo/flex, draft, blind, clash).
# ARAM / bots / events are excluded so the win-rate reflects SR performance.
SR_QUEUES = {400, 420, 430, 440, 700}

# Match-history endpoints. The current-summoner path needs no id; the puuid path
# (used by lobby scouting for *other* players) substitutes a resolved puuid.
CURRENT_SUMMONER_MATCHES = (
    "/lol-match-history/v1/products/lol/current-summoner/matches")


def puuid_matches_path(puuid: str) -> str:
    return f"/lol-match-history/v1/products/lol/{puuid}/matches"


def champion_stats(client: LCUClient, count: int = 120) -> dict[int, dict]:
    """Aggregate ``{championId: {"games": n, "wins": w}}`` over the last
    ``count`` Summoner's Rift games. Returns ``{}`` if history is unavailable."""
    games = _fetch_games(client, count)
    if not games:
        return {}
    stats: dict[int, dict] = {}
    for game in games:
        if game.get("queueId") not in SR_QUEUES:
            continue
        parts = game.get("participants") or []
        if not parts:
            continue
        me = parts[0]
        cid = me.get("championId")
        if not cid:
            continue
        bucket = stats.setdefault(cid, {"games": 0, "wins": 0})
        bucket["games"] += 1
        if (me.get("stats") or {}).get("win"):
            bucket["wins"] += 1
    return stats


def _norm_lane(lane: str | None, role: str | None) -> str:
    """LCU lane/role -> normalized role vocab (top/jungle/middle/bottom/utility)."""
    lane = (lane or "").upper()
    role = (role or "").upper()
    if lane == "TOP":
        return "top"
    if lane == "JUNGLE":
        return "jungle"
    if lane in ("MIDDLE", "MID"):
        return "middle"
    if lane == "BOTTOM":
        return "utility" if role == "DUO_SUPPORT" else "bottom"
    return ""


def _derive_timeline(st: dict) -> list[dict]:
    """A few highlight 'events' derived from the summary stats (the match-list
    endpoint carries no real timeline frames)."""
    events: list[dict] = []
    if st.get("firstBloodKill"):
        events.append({"time": 0, "event": "First Blood"})
    spree = st.get("largestKillingSpree", 0) or 0
    if spree >= 3:
        events.append({"time": 0, "event": f"{spree}-kill spree"})
    multi = st.get("largestMultiKill", 0) or 0
    if multi >= 3:
        events.append({"time": 0, "event": {3: "Triple Kill", 4: "Quadra Kill"}.get(multi, "Penta Kill")})
    return events


def normalize_game(g: dict) -> dict | None:
    """One raw LCU match → the normalized dict the rest of the app consumes
    (KDA, stats, timeline). Returns ``None`` for non-SR games or games with no
    usable participant. The summoner whose history this is appears as
    ``participants[0]``. Shared by ``recent_games`` and lobby scouting."""
    if g.get("queueId") not in SR_QUEUES:
        return None
    parts = g.get("participants") or []
    if not parts:
        return None
    me = parts[0]
    cid = me.get("championId")
    if not cid:
        return None
    st = me.get("stats") or {}
    tl = me.get("timeline") or {}
    dur = g.get("gameDuration", 0) or 0
    cs = (st.get("totalMinionsKilled", 0) or 0) + (st.get("neutralMinionsKilled", 0) or 0)
    return {
        "game_id": str(g.get("gameId")),
        "champion_id": cid,
        "role": _norm_lane(tl.get("lane"), tl.get("role")),
        "result": "Win" if st.get("win") else "Loss",
        "kda": {"kills": st.get("kills", 0), "deaths": st.get("deaths", 0),
                "assists": st.get("assists", 0)},
        "stats": {
            "duration": dur,
            "gold": st.get("goldEarned", 0),
            "total_damage": st.get("totalDamageDealtToChampions", 0),
            "damage_taken": st.get("totalDamageTaken", 0),
            "vision_score": st.get("visionScore", 0),
            "cs": cs,
            "cs_per_min": round(cs / (dur / 60), 1) if dur else 0.0,
        },
        "timeline": _derive_timeline(st),
        "played_at": g.get("gameCreation", 0),  # ms epoch
    }


def recent_games(client: LCUClient, count: int = 10) -> list[dict]:
    """The last ``count`` SR games as normalized dicts (KDA, stats, timeline),
    newest first. Feeds the v2 match-history store + post-game analysis."""
    games = _fetch_games(client, max(count * 2, 20))
    games.sort(key=lambda g: g.get("gameCreation", 0), reverse=True)
    out: list[dict] = []
    for g in games:
        normalized = normalize_game(g)
        if normalized is None:
            continue
        out.append(normalized)
        if len(out) >= count:
            break
    return out


def _fetch_games(client: LCUClient, count: int,
                 path: str = CURRENT_SUMMONER_MATCHES) -> list[dict]:
    """Page through a match-history endpoint, de-duplicating by gameId. Some
    client versions ignore begIndex/endIndex and keep returning the first page,
    so we stop as soon as a page contributes no new games (otherwise the same
    games would be counted once per page). ``path`` selects whose history to
    page (current summoner by default; a puuid path for lobby scouting)."""
    page = 20
    sep = "&" if "?" in path else "?"
    seen: dict[int, dict] = {}
    for beg in range(0, count, page):
        data = client.get_json(
            f"{path}{sep}begIndex={beg}&endIndex={beg + page - 1}"
        )
        batch = ((data or {}).get("games") or {}).get("games") or []
        if not batch:
            break
        before = len(seen)
        for g in batch:
            gid = g.get("gameId")
            if gid is not None:
                seen[gid] = g
        if len(seen) == before:   # page added nothing new → pagination exhausted
            break
        if len(batch) < page:
            break
    return list(seen.values())
