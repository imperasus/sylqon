"""Apex-league leaderboard (League-V4 challenger / grandmaster / master),
cached per queue+platform+tier on a TTL.

Official public Riot ladder data, shown as-is (LP-ranked). League-V4 apex
entries carry only a ``puuid`` (no summoner name or id), so display names come
from Account-V1 — quota-frugally: at most RESOLVE_PER_REFRESH uncached rows per
snapshot refresh (1 call each), cached permanently in ``resolved_riot_ids``, so
the ladder fills in progressively and a warm board costs zero extra calls.
Unresolved rows render as a placeholder until a later refresh reaches them.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import regions
from app.models import LeaderboardSnapshot, ResolvedRiotId

log = logging.getLogger(__name__)

TIERS = ("CHALLENGER", "GRANDMASTER", "MASTER")
QUEUES = {"RANKED_SOLO_5x5": "Solo/Duo", "RANKED_FLEX_SR": "Flex"}
DEFAULT_QUEUE = "RANKED_SOLO_5x5"
TTL_SECONDS = 1800  # apex ladders move slowly; one snapshot serves everyone
TOP_N = 100
RESOLVE_PER_REFRESH = 20  # uncached Riot-ID lookups per refresh (1 call each)


def _winrate(wins: int, losses: int) -> int | None:
    total = wins + losses
    return round(wins / total * 100) if total else None


def _shape(league: dict) -> dict:
    entries = list(league.get("entries", []))
    entries.sort(key=lambda e: -(e.get("leaguePoints") or 0))
    rows = []
    for i, e in enumerate(entries[:TOP_N], start=1):
        wins, losses = e.get("wins", 0), e.get("losses", 0)
        rows.append({
            "rank": i,
            "name": e.get("summonerName") or "",  # apex entries no longer carry one
            "puuid": e.get("puuid"),
            "lp": e.get("leaguePoints"),
            "wins": wins,
            "losses": losses,
            "winrate": _winrate(wins, losses),
            "hot_streak": bool(e.get("hotStreak")),
        })
    return {"tier": league.get("tier"), "rows": rows}


def _resolve_names(session: Session, riot, rows: list[dict], platform: str) -> None:
    """Fill Riot IDs in place: cache hits are free for every row; at most
    RESOLVE_PER_REFRESH uncached rows are looked up live (Account-V1 by puuid,
    1 call each), walking down the ladder — so the board completes over a few
    refreshes. Per-row failures leave the placeholder for the next refresh."""
    cluster = regions.cluster_for(platform)
    budget = RESOLVE_PER_REFRESH
    for r in rows:
        if r["name"] or not r.get("puuid"):
            continue
        cached = session.get(ResolvedRiotId, r["puuid"])
        if cached:
            r["name"] = cached.riot_id
            continue
        if budget <= 0:
            continue
        budget -= 1
        try:
            account = riot.get_account_by_puuid(r["puuid"], region=cluster)
        except Exception as exc:  # resolution must never break the ladder
            log.warning("name resolution failed for %s: %s", r["puuid"], exc)
            continue
        if account and account.get("gameName"):
            riot_id = f'{account["gameName"]}#{account.get("tagLine", "")}'
            r["name"] = riot_id
            session.merge(ResolvedRiotId(
                puuid=r["puuid"], platform=platform, riot_id=riot_id))


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
    _resolve_names(session, riot, payload["rows"], platform)
    session.merge(LeaderboardSnapshot(
        queue=queue, platform=platform, tier=tier,
        payload=payload, fetched_at=datetime.now(timezone.utc),
    ))
    session.commit()
    return payload
