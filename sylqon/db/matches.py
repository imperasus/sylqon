"""Match-history persistence: LCU recent games -> SQLite, and serialization.

Kept separate from ``queries.py`` (read helpers) because these compose an LCU
read with a DB write. Dedup is by ``game_id`` (the LCU sometimes ignores
pagination — see [[lcu-match-history]]).
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from sylqon.db.schema import Champion, MatchAnalysis, MatchHistory
from sylqon.lcu.history import recent_games

log = logging.getLogger(__name__)


def champion_by_riot_key(session: Session, riot_key) -> Champion | None:
    if not riot_key:
        return None
    return session.query(Champion).filter_by(riot_key=int(riot_key)).first()


def upsert_match(session: Session, game: dict) -> MatchHistory:
    """Insert or update a single normalized game (keyed by ``game_id``)."""
    # Resolve the champion FIRST (a query) — before adding a half-built row, so
    # autoflush doesn't try to INSERT it with NOT NULL fields still unset.
    champ = champion_by_riot_key(session, game.get("champion_id"))
    pa = game.get("played_at") or 0
    row = session.query(MatchHistory).filter_by(game_id=game["game_id"]).first()
    if row is None:
        row = MatchHistory(game_id=game["game_id"],
                           played_at=datetime.utcfromtimestamp(pa / 1000) if pa else datetime.utcnow())
        session.add(row)
    row.champion_id = champ.id if champ else None
    row.role = game.get("role")
    row.result = game.get("result")
    row.kda_json = game.get("kda")
    row.stats_json = game.get("stats")
    row.timeline_json = game.get("timeline")
    row.played_at = datetime.utcfromtimestamp(pa / 1000) if pa else datetime.utcnow()
    return row


def sync_recent_matches(session: Session, client, limit: int = 10) -> int:
    """Pull the last ``limit`` SR games from the LCU and upsert them. Returns the
    number of games seen (0 if the client is unavailable)."""
    games = recent_games(client, limit)
    for g in games:
        upsert_match(session, g)
    session.flush()
    return len(games)


def serialize_analysis(analysis: MatchAnalysis) -> dict:
    return {
        "summary": analysis.summary or "",
        "strengths": analysis.strengths or [],
        "weaknesses": analysis.weaknesses or [],
        "tips": analysis.tips or [],
    }


def serialize_match(session: Session, m: MatchHistory) -> dict:
    champ = session.get(Champion, m.champion_id) if m.champion_id else None
    stats = m.stats_json or {}
    return {
        "id": m.id,
        "game_id": m.game_id,
        "champion": champ.name if champ else "Unknown",
        "slug": (champ.slug if champ else "") or "",
        "role": m.role or "",
        "result": m.result or "",
        "duration": stats.get("duration", 0),
        "kda": m.kda_json or {},
        "stats": stats,
        "timeline": m.timeline_json or [],
        "played_at": m.played_at.isoformat() if m.played_at else None,
        "has_analysis": m.analysis is not None,
    }


def match_to_analysis_input(session: Session, m: MatchHistory) -> dict:
    """Shape a stored match into the dict the analyzer prompt expects."""
    champ = session.get(Champion, m.champion_id) if m.champion_id else None
    stats = m.stats_json or {}
    return {
        "champion": champ.name if champ else "Unknown",
        "role": m.role or "",
        "result": m.result or "",
        "duration": stats.get("duration", 0),
        "kda": m.kda_json or {},
        "stats": stats,
        "timeline": m.timeline_json or [],
    }
