"""Own-data champion build + matchup aggregation for the /build and /matchup
commands (S10). Honest by design: below the minimum sample count the caller
gets None and the bot says "not enough data yet" — the numbers sharpen as the
crawl widens, and no external scraping is involved (hosted products are
official-API-only from day one).
"""
from __future__ import annotations

from collections import Counter

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, aliased

from app.advice import benchmarks
from app.models import Match, MatchParticipant

MIN_BUILD_GAMES = 3
MIN_MATCHUP_GAMES = 2
SR_QUEUES = [420, 440, 400, 430]


def champion_index(session: Session) -> list[dict]:
    """Per-champion presence, win rate and main role for the meta index page —
    one SQL aggregate over typed columns. The page previously looped
    build_for_champion over every champion, loading each participant's stats
    JSONB; at crawled-dataset scale that killed the API process."""
    rows = session.execute(
        select(MatchParticipant.champion_name, MatchParticipant.team_position,
               func.count(),
               func.sum(case((MatchParticipant.win.is_(True), 1), else_=0)))
        .join(Match, Match.match_id == MatchParticipant.match_id)
        .where(Match.queue_id.in_(SR_QUEUES),
               MatchParticipant.champion_name.isnot(None),
               MatchParticipant.champion_name != "")
        .group_by(MatchParticipant.champion_name, MatchParticipant.team_position)
    ).all()

    by_champ: dict[str, dict] = {}
    for name, role, games, wins in rows:
        c = by_champ.setdefault(name, {"champion": name, "games": 0, "wins": 0,
                                       "roles": Counter()})
        c["games"] += games
        c["wins"] += int(wins or 0)
        c["roles"][role or "?"] += games

    out = []
    for c in by_champ.values():
        if c["games"] < MIN_BUILD_GAMES:
            continue
        out.append({
            "champion": c["champion"],
            "games": c["games"],
            "winrate_pct": round(c["wins"] / c["games"] * 100),
            "role": c["roles"].most_common(1)[0][0],
        })
    out.sort(key=lambda d: -d["games"])
    return out


def champion_names(session: Session, prefix: str = "") -> list[str]:
    rows = session.execute(select(MatchParticipant.champion_name).distinct())
    names = sorted({r[0] for r in rows if r[0]})
    if prefix:
        names = [n for n in names if n.lower().startswith(prefix.lower())]
    return names


def build_for_champion(session: Session, champion: str) -> dict | None:
    """Games, win rate, main role and core-item build rates for one champion.

    Only the six item-slot ids are extracted from the stats JSONB in SQL
    (portable across Postgres and SQLite) — loading each participant's full
    stats payload made the public champion page take seconds at
    crawled-dataset scale."""
    item_cols = [MatchParticipant.stats[f"item{slot}"].as_integer()
                 for slot in range(6)]
    rows = session.execute(
        select(MatchParticipant.champion_name, MatchParticipant.team_position,
               MatchParticipant.win, *item_cols)
        .join(Match, Match.match_id == MatchParticipant.match_id)
        # lower() equality, not ilike: Postgres can serve the former from the
        # ix_participants_champ_lower expression index; ilike always seq-scans.
        .where(func.lower(MatchParticipant.champion_name) == champion.lower())
        .where(Match.queue_id.in_(SR_QUEUES))
    ).all()
    if len(rows) < MIN_BUILD_GAMES:
        return None

    wins = 0
    items: Counter = Counter()
    roles: Counter = Counter()
    for _, role, win, *slot_items in rows:
        wins += 1 if win else 0
        roles[role or "?"] += 1
        for item_id in slot_items:
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


def champion_matchups(session: Session, champion: str, role: str) -> list[tuple[str, int, int]]:
    """``(opponent, games, winrate_pct)`` lane records for one champion in one
    role, most-played first — the champion page's matchup table.

    Same pairing rules as ``pool.role_dataset`` (same match, same
    teamPosition, opposite teams, exactly two such laners in the match), but
    anchored to one champion up front: the page previously built every lane
    pairing in the role via role_dataset and threw away all but one champion's
    rows — a multi-second aggregate at crawled-dataset scale.
    """
    a, b, c = aliased(MatchParticipant), aliased(MatchParticipant), aliased(MatchParticipant)
    # The well-formed-SR guard from role_dataset, per anchored row: exactly
    # two named laners share this match+position, so pairings stay 1:1.
    laners = (
        select(func.count())
        .where(c.match_id == a.match_id,
               c.team_position == a.team_position,
               c.champion_name.isnot(None), c.champion_name != "")
        .correlate(a)
        .scalar_subquery()
    )
    rows = session.execute(
        select(b.champion_name, func.count(),
               func.sum(case((a.win.is_(True), 1), else_=0)))
        .select_from(a)
        .join(b, (b.match_id == a.match_id)
              & (b.team_position == a.team_position)
              & (b.team_id != a.team_id))
        .join(Match, Match.match_id == a.match_id)
        .where(Match.queue_id.in_(SR_QUEUES),
               func.lower(a.champion_name) == champion.lower(),
               a.team_position == role,
               b.champion_name.isnot(None), b.champion_name != "",
               laners == 2)
        .group_by(b.champion_name)
    ).all()
    records = [(name, games, round(int(wins or 0) / games * 100))
               for name, games, wins in rows if games >= MIN_MATCHUP_GAMES]
    records.sort(key=lambda r: -r[1])
    return records


def matchup(session: Session, champ_a: str, champ_b: str) -> dict | None:
    """Lane-opponent record: same match, same teamPosition, opposite teams.

    One self-join aggregate over typed columns (the pool.role_dataset pattern)
    — the previous version loaded every stored MatchParticipant row of both
    champions, stats JSONB included, and paired them in Python; at
    crawled-dataset scale that made the bot command slow and memory-heavy.
    """
    a, b = aliased(MatchParticipant), aliased(MatchParticipant)
    games, a_wins = session.execute(
        select(func.count(), func.sum(case((a.win.is_(True), 1), else_=0)))
        .select_from(a)
        .join(b, (b.match_id == a.match_id)
              & (b.team_id != a.team_id)
              & (b.team_position.is_not_distinct_from(a.team_position)))
        .join(Match, Match.match_id == a.match_id)
        .where(Match.queue_id.in_(SR_QUEUES),
               func.lower(a.champion_name) == champ_a.lower(),
               func.lower(b.champion_name) == champ_b.lower())
    ).one()
    a_wins = int(a_wins or 0)

    if games < MIN_MATCHUP_GAMES:
        return None
    return {
        "champ_a": champ_a,
        "champ_b": champ_b,
        "games": games,
        "a_wins": a_wins,
        "a_winrate_pct": round(a_wins / games * 100),
    }
