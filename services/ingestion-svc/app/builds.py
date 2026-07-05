"""Own-data champion build + matchup aggregation for the /build and /matchup
commands (S10). Honest by design: below the minimum sample count the caller
gets None and the bot says "not enough data yet" — the numbers sharpen as the
crawl widens, and no external scraping is involved (hosted products are
official-API-only from day one).
"""
from __future__ import annotations

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.advice import benchmarks
from app.models import Match, MatchParticipant

MIN_BUILD_GAMES = 3
MIN_MATCHUP_GAMES = 2


def champion_names(session: Session, prefix: str = "") -> list[str]:
    rows = session.execute(select(MatchParticipant.champion_name).distinct())
    names = sorted({r[0] for r in rows if r[0]})
    if prefix:
        names = [n for n in names if n.lower().startswith(prefix.lower())]
    return names


def build_for_champion(session: Session, champion: str) -> dict | None:
    rows = list(
        session.execute(
            select(MatchParticipant)
            .join(Match, Match.match_id == MatchParticipant.match_id)
            .where(MatchParticipant.champion_name.ilike(champion))
            .where(Match.queue_id.in_([420, 440, 400, 430]))
        ).scalars()
    )
    if len(rows) < MIN_BUILD_GAMES:
        return None

    wins = sum(1 for p in rows if p.win)
    items: Counter = Counter()
    roles: Counter = Counter()
    for p in rows:
        roles[p.team_position or "?"] += 1
        for slot in range(6):
            item_id = p.stats.get(f"item{slot}")
            if item_id and item_id in benchmarks.CORE_ITEM_IDS:
                items[item_id] += 1

    return {
        "champion": rows[0].champion_name,
        "games": len(rows),
        "wins": wins,
        "winrate_pct": round(wins / len(rows) * 100),
        "role": roles.most_common(1)[0][0],
        "core_items": [
            {
                "id": item_id,
                "name": benchmarks.CORE_ITEM_NAMES.get(item_id, str(item_id)),
                "games": n,
                "pct": round(n / len(rows) * 100),
            }
            for item_id, n in items.most_common(6)
        ],
    }


def matchup(session: Session, champ_a: str, champ_b: str) -> dict | None:
    """Lane-opponent record: same match, same teamPosition, opposite teams."""
    rows = list(
        session.execute(
            select(MatchParticipant)
            .join(Match, Match.match_id == MatchParticipant.match_id)
            .where(
                MatchParticipant.champion_name.ilike(champ_a)
                | MatchParticipant.champion_name.ilike(champ_b)
            )
            .where(Match.queue_id.in_([420, 440, 400, 430]))
        ).scalars()
    )
    by_match: dict[str, list[MatchParticipant]] = {}
    for p in rows:
        by_match.setdefault(p.match_id, []).append(p)

    games = a_wins = 0
    for participants in by_match.values():
        a_list = [p for p in participants if p.champion_name.lower() == champ_a.lower()]
        b_list = [p for p in participants if p.champion_name.lower() == champ_b.lower()]
        for pa in a_list:
            for pb in b_list:
                if pa.team_id != pb.team_id and pa.team_position == pb.team_position:
                    games += 1
                    a_wins += 1 if pa.win else 0

    if games < MIN_MATCHUP_GAMES:
        return None
    return {
        "champ_a": champ_a,
        "champ_b": champ_b,
        "games": games,
        "a_wins": a_wins,
        "a_winrate_pct": round(a_wins / games * 100),
    }
