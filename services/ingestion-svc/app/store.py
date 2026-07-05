"""Idempotent persistence for match bundles.

``INSERT ... ON CONFLICT DO NOTHING`` on both Postgres and SQLite dialects, so
the same code path is unit-tested offline on SQLite and runs on Postgres live.
A bundle (match + participants + timeline) is written in one transaction —
either the whole match lands or none of it, so a rerun can always retry cleanly.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Advice, Match, MatchParticipant, Timeline


def _insert_ignore(session: Session, table):
    if session.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return insert(table).on_conflict_do_nothing()


def derive_patch(game_version: str | None) -> str | None:
    """'14.23.634.7472' → '14.23' (benchmark bucketing key)."""
    if not game_version:
        return None
    parts = game_version.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else game_version


def match_exists(session: Session, match_id: str) -> bool:
    return session.scalar(select(Match.match_id).where(Match.match_id == match_id)) is not None


def timeline_exists(session: Session, match_id: str) -> bool:
    return (
        session.scalar(select(Timeline.match_id).where(Timeline.match_id == match_id))
        is not None
    )


def insert_match_bundle(
    session: Session, match: dict, timeline: dict, region: str
) -> bool:
    """Insert one match + participants + timeline atomically.

    Returns True if the match row was newly inserted, False when it already
    existed (nothing else is touched then — participants/timeline are only ever
    written together with their match row).
    """
    match_id = match.get("metadata", {}).get("matchId")
    info = match.get("info", {})
    if not match_id or not info:
        raise ValueError("match payload missing metadata.matchId or info")

    game_version = info.get("gameVersion")
    result = session.execute(
        _insert_ignore(session, Match).values(
            match_id=match_id,
            platform=match_id.split("_", 1)[0],
            region=region,
            queue_id=info.get("queueId"),
            game_creation=info.get("gameCreation"),
            game_duration=info.get("gameDuration"),
            game_version=game_version,
            patch=derive_patch(game_version),
            raw=info,
        )
    )
    if result.rowcount == 0:
        session.rollback()
        return False

    participant_rows = [
        {
            "match_id": match_id,
            "puuid": p.get("puuid"),
            "participant_id": p.get("participantId"),
            "team_id": p.get("teamId"),
            "champion_id": p.get("championId"),
            "champion_name": p.get("championName"),
            "team_position": p.get("teamPosition"),
            "win": p.get("win"),
            "kills": p.get("kills"),
            "deaths": p.get("deaths"),
            "assists": p.get("assists"),
            "gold_earned": p.get("goldEarned"),
            "total_minions_killed": p.get("totalMinionsKilled"),
            "neutral_minions_killed": p.get("neutralMinionsKilled"),
            "vision_score": p.get("visionScore"),
            "wards_placed": p.get("wardsPlaced"),
            "control_wards_bought": p.get("visionWardsBoughtInGame"),
            "damage_to_champions": p.get("totalDamageDealtToChampions"),
            "stats": p,
        }
        for p in info.get("participants", [])
        if p.get("puuid")
    ]
    if participant_rows:
        session.execute(_insert_ignore(session, MatchParticipant), participant_rows)

    session.execute(
        _insert_ignore(session, Timeline).values(
            match_id=match_id, payload=timeline.get("info", timeline)
        )
    )
    session.commit()
    return True


def get_match_with_timeline(session: Session, match_id: str) -> tuple[Match, Timeline] | None:
    match = session.get(Match, match_id)
    timeline = session.get(Timeline, match_id)
    if match is None or timeline is None:
        return None
    return match, timeline


def get_participant(session: Session, match_id: str, puuid: str) -> MatchParticipant | None:
    return session.get(MatchParticipant, (match_id, puuid))


def get_cached_advice(session: Session, match_id: str, puuid: str) -> Advice | None:
    return session.scalar(
        select(Advice).where(Advice.match_id == match_id, Advice.puuid == puuid)
    )


def save_advice(
    session: Session,
    match_id: str,
    puuid: str,
    top_finding: dict,
    all_findings: list,
    text_hu: str,
    text_en: str,
) -> Advice:
    advice = Advice(
        match_id=match_id,
        puuid=puuid,
        top_finding=top_finding,
        all_findings=all_findings,
        text_hu=text_hu,
        text_en=text_en,
    )
    session.add(advice)
    session.commit()
    return advice
