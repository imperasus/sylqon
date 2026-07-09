"""Apex-league leaderboard (League-V4 challenger / grandmaster / master),
cached per queue+platform+tier on a TTL.

Official public Riot ladder data, shown as-is (LP-ranked). Riot's league entries
no longer carry the summoner's Riot ID reliably (post Riot-ID migration), so a
blank name renders as a short summoner id — name resolution (summoner id → puuid
→ Riot ID) is a later enhancement, deliberately skipped to avoid a per-refresh
fan-out of hundreds of calls.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import LeaderboardSnapshot

TIERS = ("CHALLENGER", "GRANDMASTER", "MASTER")
QUEUES = {"RANKED_SOLO_5x5": "Solo/Duo", "RANKED_FLEX_SR": "Flex"}
DEFAULT_QUEUE = "RANKED_SOLO_5x5"
TTL_SECONDS = 1800  # apex ladders move slowly; one snapshot serves everyone
TOP_N = 100


def _winrate(wins: int, losses: int) -> int | None:
    total = wins + losses
    return round(wins / total * 100) if total else None


def _shape(league: dict) -> dict:
    entries = list(league.get("entries", []))
    entries.sort(key=lambda e: -(e.get("leaguePoints") or 0))
    rows = []
    for i, e in enumerate(entries[:TOP_N], start=1):
        wins, losses = e.get("wins", 0), e.get("losses", 0)
        name = e.get("summonerName") or ""
        if not name and e.get("summonerId"):
            name = e["summonerId"][:8] + "…"
        rows.append({
            "rank": i,
            "name": name,
            "lp": e.get("leaguePoints"),
            "wins": wins,
            "losses": losses,
            "winrate": _winrate(wins, losses),
            "hot_streak": bool(e.get("hotStreak")),
        })
    return {"tier": league.get("tier"), "rows": rows}


def _fresh(snap: LeaderboardSnapshot, ttl: int) -> bool:
    fetched = snap.fetched_at
    if fetched.tzinfo is None:  # SQLite hands back naive datetimes
        fetched = fetched.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - fetched).total_seconds() < ttl


def get_leaderboard(session: Session, riot, tier: str, queue: str, platform: str,
                    ttl: int = TTL_SECONDS) -> dict | None:
    """Cached apex ladder for (queue, platform, tier). Serves a fresh snapshot;
    otherwise fetches from League-V4, caches, and returns it. Falls back to a
    stale snapshot if the live fetch fails."""
    tier = tier.upper()
    snap = session.get(LeaderboardSnapshot, (queue, platform, tier))
    if snap and _fresh(snap, ttl):
        return snap.payload

    league = riot.get_apex_league(tier, queue, platform=platform)
    if not isinstance(league, dict):
        return snap.payload if snap else None

    payload = _shape(league)
    session.merge(LeaderboardSnapshot(
        queue=queue, platform=platform, tier=tier,
        payload=payload, fetched_at=datetime.now(timezone.utc),
    ))
    session.commit()
    return payload
