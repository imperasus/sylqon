"""Bulk sync bundle — everything the local app's full sync needs, from our own
aggregation, in one response: per-role meta stats (tier/WR/presence), the
op.gg-shaped build payload, lane counters and same-team synergies.

This mirrors the exact contract of the local ``sylqon/mcp/opgg_http`` module
(fetch_all_meta / fetch_detail / fetch_synergies), so the local full sync can
switch source without changing its loop — the final step of the op.gg exit.
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import metabuild
from app.advice import benchmarks
from app.models import Match

log = logging.getLogger(__name__)

SR_QUEUES = {420, 440, 400, 430}
ROLES = ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")

MIN_ENTRY_GAMES = 8      # champ+role presence needed to appear in the bundle
MIN_COUNTER_GAMES = 3    # lane pairing evidence for a counter entry
MIN_SYNERGY_GAMES = 4    # shared-team games for a synergy entry


def _tier(win_rate: float, games: int) -> int:
    """0=S+, 1=S, 2=A, 3=B — own-data buckets, generous below big samples."""
    if games >= 20 and win_rate >= 0.54:
        return 0
    if win_rate >= 0.52:
        return 1
    if win_rate >= 0.49:
        return 2
    return 3


def sync_aggregates(session: Session) -> dict:
    """One pass over stored SR matches → everything but the build payloads."""
    champ_id: dict[str, Counter] = defaultdict(Counter)          # name → championId votes
    stats: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])   # (role,name)
    matchups: dict[tuple[str, str, str], list[int]] = defaultdict(lambda: [0, 0])  # (role,a,b)
    pairs: dict[tuple[str, str, str], list[int]] = defaultdict(lambda: [0, 0])     # (role,name,ally)
    role_matches: Counter = Counter()

    for match in session.execute(select(Match)).scalars():
        if match.queue_id not in SR_QUEUES:
            continue
        parts = [p for p in match.raw.get("participants", [])
                 if p.get("championName") and p.get("teamPosition") in ROLES]
        by_role: dict[str, list[dict]] = defaultdict(list)
        for p in parts:
            champ_id[p["championName"]][p.get("championId")] += 1
            role = p["teamPosition"]
            by_role[role].append(p)
            entry = stats[(role, p["championName"])]
            entry[0] += 1
            entry[1] += 1 if p.get("win") else 0
        for role, laners in by_role.items():
            role_matches[role] += 1
            if len(laners) == 2 and laners[0].get("teamId") != laners[1].get("teamId"):
                a, b = laners
                m = matchups[(role, a["championName"], b["championName"])]
                m[0] += 1
                m[1] += 1 if a.get("win") else 0
                m = matchups[(role, b["championName"], a["championName"])]
                m[0] += 1
                m[1] += 1 if b.get("win") else 0
        for p in parts:
            for ally in parts:
                if ally is p or ally.get("teamId") != p.get("teamId"):
                    continue
                e = pairs[(p["teamPosition"], p["championName"], ally["championName"])]
                e[0] += 1
                e[1] += 1 if p.get("win") else 0

    return {
        "champ_id": {name: c.most_common(1)[0][0] for name, c in champ_id.items()
                     if c.most_common(1)[0][0]},
        "stats": stats,
        "matchups": matchups,
        "pairs": pairs,
        "role_matches": role_matches,
    }


def build_sync_bundle(session: Session, min_games: int = MIN_ENTRY_GAMES,
                      with_payloads: bool = True) -> dict:
    agg = sync_aggregates(session)
    ids = agg["champ_id"]
    entries = []
    for (role, name), (games, wins) in sorted(
        agg["stats"].items(), key=lambda kv: -kv[1][0]
    ):
        if games < min_games or name not in ids:
            continue
        wr = wins / games
        presence = games / max(1, 2 * agg["role_matches"][role])

        counters = []
        for (r, a, b), (mg, mw) in agg["matchups"].items():
            if r == role and a == name and mg >= MIN_COUNTER_GAMES and b in ids:
                counters.append({"champion_id": ids[b], "opp_winrate": round(mw / mg, 3)})
        counters.sort(key=lambda c: c["opp_winrate"])  # worst matchups first

        synergies = []
        for (r, n, ally), (pg, pw) in agg["pairs"].items():
            if r == role and n == name and pg >= MIN_SYNERGY_GAMES and ally in ids:
                synergies.append({"synergy_champion_id": ids[ally],
                                  "win_rate": round(pw / pg, 3), "games": pg})
        synergies.sort(key=lambda s: (-s["win_rate"], -s["games"]))

        payload = metabuild.get_meta_build(session, name, role) if with_payloads else None
        entries.append({
            "champion_id": ids[name],
            "champion": name,
            "role": role,
            "games": games,
            "tier": _tier(wr, games),
            "win_rate": round(wr, 3),
            "pick_rate": round(presence, 4),
            "payload": payload,
            "counters": counters[:10],
            "synergies": synergies[:8],
        })

    return {"patch": benchmarks.CORE_ITEMS_PATCH, "entries": entries}
