"""Riot REST client — a port of the local app's ``sylqon/riot/api.py`` behavior
with the rate limiter replacing the concurrency semaphore, plus the Match-V5
timeline endpoint the local client does not use.

Contract (mirrors the reference): 429 → honor Retry-After, install a shared
penalty, retry the same request; 404 → ``None`` immediately; any other failure
→ warn + retry budget → ``None`` (callers treat it as a per-item failure, never
a run abort).
"""
from __future__ import annotations

import logging
import time
from urllib.parse import quote

import requests

from app import config
from app.ratelimit import RateLimiter

log = logging.getLogger(__name__)

_BASE = "https://{region}.api.riotgames.com"


class RiotClient:
    def __init__(
        self,
        rate_limiter: RateLimiter,
        api_key: str | None = None,
        mass_region: str | None = None,
        platform_region: str | None = None,
        session: requests.Session | None = None,
        sleep=time.sleep,
    ) -> None:
        self._limiter = rate_limiter
        self._api_key = api_key if api_key is not None else config.RIOT_API_KEY
        self.mass_region = mass_region or config.RIOT_MASS_REGION
        self.platform_region = platform_region or config.RIOT_PLATFORM_REGION
        self._session = session or requests.Session()
        self._sleep = sleep

    # -- plumbing ----------------------------------------------------------

    def _get(self, region: str, path: str, params: dict | None = None) -> dict | list | None:
        url = _BASE.format(region=region) + path
        for attempt in range(config.RIOT_MAX_RETRIES + 1):
            try:
                self._limiter.acquire(region)
                r = self._session.get(
                    url,
                    headers={"X-Riot-Token": self._api_key},
                    params=params,
                    timeout=config.RIOT_REQUEST_TIMEOUT,
                )
                if r.status_code == 429:
                    retry_after = float(r.headers.get("Retry-After", 2))
                    log.warning("Riot API rate-limited (%s), waiting %.1fs", region, retry_after)
                    self._limiter.on_rate_limit_exceeded(region, retry_after)
                    self._sleep(retry_after)
                    continue
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                return r.json()
            except requests.RequestException as exc:
                log.warning("Riot API request failed (attempt %d, %s): %s", attempt + 1, path, exc)
        return None

    # -- endpoints (all Phase 0 calls route to the mass-region cluster) -----

    def get_account_by_riot_id(self, game_name: str, tag_line: str,
                               region: str | None = None) -> dict | None:
        """ACCOUNT-V1: Riot ID → {puuid, gameName, tagLine}. ``region`` is the
        regional cluster (default the client's mass region)."""
        if not game_name or not tag_line:
            return None
        return self._get(
            region or self.mass_region,
            "/riot/account/v1/accounts/by-riot-id/"
            f"{quote(game_name, safe='')}/{quote(tag_line, safe='')}",
        )

    def get_match_ids(self, puuid: str, count: int | None = None,
                      queue: int | None = None, region: str | None = None) -> list[str]:
        """MATCH-V5: newest match IDs for a puuid (regional cluster route)."""
        params: dict = {"count": count or config.RIOT_MATCH_COUNT}
        if queue is not None:
            params["queue"] = queue
        result = self._get(
            region or self.mass_region, f"/lol/match/v5/matches/by-puuid/{puuid}/ids", params
        )
        return result if isinstance(result, list) else []

    def get_match(self, match_id: str, region: str | None = None) -> dict | None:
        """MATCH-V5: full match object (regional cluster route)."""
        return self._get(region or self.mass_region, f"/lol/match/v5/matches/{match_id}")

    def get_timeline(self, match_id: str, region: str | None = None) -> dict | None:
        """MATCH-V5: per-minute frame/event timeline for a match (regional cluster)."""
        return self._get(
            region or self.mass_region, f"/lol/match/v5/matches/{match_id}/timeline"
        )

    def get_ranked_stats(self, puuid: str, platform: str | None = None) -> list | None:
        """LEAGUE-V4: ranked entries for a puuid (platform route, e.g. eun1)."""
        return self._get(
            platform or self.platform_region, f"/lol/league/v4/entries/by-puuid/{puuid}"
        )

    def get_apex_league(self, tier: str, queue: str = "RANKED_SOLO_5x5",
                        platform: str | None = None) -> dict | None:
        """LEAGUE-V4: challenger/grandmaster/master league list for a queue
        (platform route). ``tier`` is CHALLENGER/GRANDMASTER/MASTER."""
        path = {
            "CHALLENGER": "challengerleagues",
            "GRANDMASTER": "grandmasterleagues",
            "MASTER": "masterleagues",
        }.get(tier.upper())
        if not path:
            return None
        return self._get(
            platform or self.platform_region, f"/lol/league/v4/{path}/by-queue/{queue}"
        )

    def get_summoner_by_puuid(self, puuid: str, platform: str | None = None) -> dict | None:
        """SUMMONER-V4: {summonerLevel, profileIconId, ...} for a puuid (platform route)."""
        return self._get(
            platform or self.platform_region, f"/lol/summoner/v4/summoners/by-puuid/{puuid}"
        )

    def get_summoner_by_id(self, summoner_id: str, platform: str | None = None) -> dict | None:
        """SUMMONER-V4: summoner by encrypted summonerId (platform route) — the
        id League-V4 apex entries carry; its puuid keys the Riot-ID lookup."""
        return self._get(
            platform or self.platform_region, f"/lol/summoner/v4/summoners/{summoner_id}"
        )

    def get_account_by_puuid(self, puuid: str, region: str | None = None) -> dict | None:
        """ACCOUNT-V1: puuid → {gameName, tagLine} (regional cluster route)."""
        return self._get(
            region or self.mass_region, f"/riot/account/v1/accounts/by-puuid/{puuid}"
        )

    def get_top_mastery(self, puuid: str, count: int = 6,
                        platform: str | None = None) -> list | None:
        """CHAMPION-MASTERY-V4: top N champions by mastery points (platform route)."""
        return self._get(
            platform or self.platform_region,
            f"/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}/top",
            {"count": count},
        )
