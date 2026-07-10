"""Apex-league leaderboard (League-V4 challenger / grandmaster / master),
cached per queue+platform+tier on a TTL.

Official public Riot ladder data, shown as-is (LP-ranked). Riot's league entries
no longer carry the summoner's Riot ID (post Riot-ID migration), so names are
resolved separately — summonerId → Summoner-V4 (puuid) → Account-V1 (Riot ID) —
but quota-frugally: only the top RESOLVE_TOP rows, only at snapshot-refresh
time, and resolved ids are cached permanently in ``resolved_names`` so a warm
ladder costs zero extra calls. Unresolved entries fall back to a short id.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import regions
from app.models import LeaderboardSnapshot, ResolvedName

log = logging.getLogger(__name__)

TIERS = ("CHALLENGER", "GRANDMASTER", "MASTER")
QUEUES = {"RANKED_SOLO_5x5": "Solo/Duo", "RANKED_FLEX_SR": "Flex"}
DEFAULT_QUEUE = "RANKED_SOLO_5x5"
TTL_SECONDS = 1800  # apex ladders move slowly; one snapshot serves everyone
TOP_N = 100
RESOLVE_TOP = 20  # rows whose Riot ID we resolve per refresh (2 calls each, cold)


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
            "summoner_id": e.get("summonerId"),
            "lp": e.get("leaguePoints"),
            "wins": wins,
            "losses": losses,
            "winrate": _winrate(wins, losses),
            "hot_streak": bool(e.get("hotStreak")),
        })
    return {"tier": league.get("tier"), "rows": rows}


def _resolve_names(session: Session, riot, rows: list[dict], platform: str) -> None:
    """Fill Riot IDs for the top rows in place. Cache-first (resolved_names);
    cold entries cost 2 calls each. Per-row failures keep the short-id fallback."""
    cluster = regions.cluster_for(platform)
    for r in rows[:RESOLVE_TOP]:
        sid = r.get("summoner_id")
        if not sid or (r["name"] and not r["name"].endswith("…")):
            continue
        cached = session.get(ResolvedName, sid)
        if cached:
            r["name"] = cached.riot_id
            continue
        try:
            summoner = riot.get_summoner_by_id(sid, platform=platform)
            puuid = summoner.get("puuid") if summoner else None
            account = riot.get_account_by_puuid(puuid, region=cluster) if puuid else None
        except Exception as exc:  # resolution must never break the ladder
            log.warning("name resolution failed for %s: %s", sid, exc)
            continue
        if account and account.get("gameName"):
            riot_id = f'{account["gameName"]}#{account.get("tagLine", "")}'
            r["name"] = riot_id
            session.merge(ResolvedName(
                summoner_id=sid, platform=platform, puuid=puuid, riot_id=riot_id))


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
