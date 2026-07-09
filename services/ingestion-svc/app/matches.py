"""Read-only views over stored matches for the public web.

- ``list_for_puuid`` — the player's recent matches as summary rows (match-list page)
- ``detail`` — one match's two-team scoreboard (match-detail page)

Reads only what ingestion already persisted (``Match.raw`` + ``MatchParticipant``);
no Riot calls here. Everything is descriptive display of the player's own official
match data (KDA, CS, gold, vision) — never a skill/MMR estimate.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import champions
from app.models import Match, MatchParticipant

# queueId → human label; anything else renders as "Other".
QUEUE_LABELS = {
    400: "Normal Draft", 420: "Ranked Solo/Duo", 430: "Normal Blind",
    440: "Ranked Flex", 450: "ARAM", 490: "Quickplay", 700: "Clash",
    720: "ARAM Clash", 830: "Co-op vs AI", 840: "Co-op vs AI", 850: "Co-op vs AI",
    900: "ARURF", 1020: "One for All", 1700: "Arena", 1900: "URF",
}


def queue_label(queue_id: int | None) -> str:
    return QUEUE_LABELS.get(queue_id, "Other")


def _cs(minions: int | None, neutral: int | None) -> int:
    return (minions or 0) + (neutral or 0)


def list_for_puuid(session: Session, puuid: str, limit: int = 20) -> list[dict]:
    """The player's most recent stored matches, newest first."""
    rows = session.execute(
        select(MatchParticipant, Match)
        .join(Match, Match.match_id == MatchParticipant.match_id)
        .where(MatchParticipant.puuid == puuid)
        .order_by(Match.game_creation.desc())
        .limit(limit)
    ).all()

    out = []
    for p, m in rows:
        cs = _cs(p.total_minions_killed, p.neutral_minions_killed)
        minutes = (m.game_duration or 0) / 60
        out.append({
            "match_id": p.match_id,
            "champion_id": p.champion_id,
            "champion": p.champion_name,
            "champion_url": champions.square_url(p.champion_id),
            "win": p.win,
            "kills": p.kills, "deaths": p.deaths, "assists": p.assists,
            "cs": cs,
            "cs_per_min": round(cs / minutes, 1) if minutes else None,
            "role": p.team_position,
            "queue": queue_label(m.queue_id),
            "duration": m.game_duration,
            "created": m.game_creation,
        })
    return out


def _participant_view(p: dict) -> dict:
    name = (f"{p.get('riotIdGameName', '')}#{p.get('riotIdTagline', '')}".strip("#")
            or p.get("summonerName") or "")
    items = [champions.item_url(p.get(f"item{i}")) for i in range(7)]
    return {
        "champion_id": p.get("championId"),
        "champion": p.get("championName"),
        "champion_url": champions.square_url(p.get("championId")),
        "name": name,
        "role": p.get("teamPosition"),
        "kills": p.get("kills"), "deaths": p.get("deaths"), "assists": p.get("assists"),
        "cs": _cs(p.get("totalMinionsKilled"), p.get("neutralMinionsKilled")),
        "gold": p.get("goldEarned"),
        "damage": p.get("totalDamageDealtToChampions"),
        "vision": p.get("visionScore"),
        "items": [u for u in items if u],
    }


def detail(session: Session, match_id: str) -> dict | None:
    """One match's two-team scoreboard from the stored raw payload, or None."""
    match = session.get(Match, match_id)
    if match is None:
        return None
    participants = match.raw.get("participants", [])

    teams = []
    for team_id in (100, 200):
        members = [_participant_view(p) for p in participants
                   if p.get("teamId") == team_id]
        team_row = next((p for p in participants if p.get("teamId") == team_id), {})
        teams.append({
            "team_id": team_id,
            "win": bool(team_row.get("win")),
            "kills": sum(m["kills"] or 0 for m in members),
            "gold": sum(m["gold"] or 0 for m in members),
            "participants": members,
        })

    return {
        "match_id": match_id,
        "queue": queue_label(match.queue_id),
        "duration": match.game_duration,
        "created": match.game_creation,
        "patch": match.patch,
        "teams": teams,
    }
