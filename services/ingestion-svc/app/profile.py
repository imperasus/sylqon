"""Summoner profile assembly — Account-V1 + Summoner-V4 + League-V4 + Mastery-V4
composed into one display DTO for the public web profile page and the
``/api/summoner/...`` JSON endpoint.

Riot-ID first (Account-V1): summoner-by-name is deprecated, so every lookup goes
Name#TAG → PUUID → the platform-routed detail calls. Every sub-call degrades
gracefully: a missing account returns None; a transient failure on rank / level /
mastery just leaves that slice empty rather than failing the whole profile.

ToS framing: this is descriptive display of the player's own official Riot data
(level, rank as Riot publishes it, mastery) — never a skill/MMR estimate.
"""
from __future__ import annotations

from app import champions, regions

# League-V4 queueType → human label, in display order.
_QUEUE_LABELS = {
    "RANKED_SOLO_5x5": "Ranked Solo/Duo",
    "RANKED_FLEX_SR": "Ranked Flex",
}


def _winrate(wins: int, losses: int) -> int | None:
    total = wins + losses
    return round(wins / total * 100) if total else None


def _ranked(entries: list | None) -> list[dict]:
    by_queue = {e.get("queueType"): e for e in (entries or []) if isinstance(e, dict)}
    out = []
    for queue, label in _QUEUE_LABELS.items():
        e = by_queue.get(queue)
        if not e:
            continue
        wins, losses = e.get("wins", 0), e.get("losses", 0)
        out.append({
            "queue": queue,
            "label": label,
            "tier": e.get("tier"),
            "division": e.get("rank"),
            "lp": e.get("leaguePoints"),
            "wins": wins,
            "losses": losses,
            "winrate": _winrate(wins, losses),
        })
    return out


def _top_champions(masteries: list | None) -> list[dict]:
    out = []
    for m in masteries or []:
        if not isinstance(m, dict):
            continue
        cid = m.get("championId")
        out.append({
            "champion_id": cid,
            "name": champions.name_for(cid) or f"Champion {cid}",
            "square_url": champions.square_url(cid),
            "mastery_points": m.get("championPoints"),
            "mastery_level": m.get("championLevel"),
        })
    return out


def build_profile(riot, game_name: str, tag_line: str, platform: str | None = None,
                  mastery_count: int = 6) -> dict | None:
    """Assemble the profile DTO, or None if the Riot ID resolves to no account.

    ``platform`` (euw1, na1, …) routes Account-V1 to its cluster and the
    Summoner/League/Mastery calls to that platform; defaults to the client's
    configured region. ``riot`` is any object exposing the RiotClient surface —
    the real client in production, a stub in tests.
    """
    cluster = regions.cluster_for(platform) if platform else None
    account = riot.get_account_by_riot_id(game_name, tag_line, region=cluster)
    if not account or not account.get("puuid"):
        return None
    puuid = account["puuid"]

    summoner = riot.get_summoner_by_puuid(puuid, platform=platform) or {}
    ranked = _ranked(riot.get_ranked_stats(puuid, platform=platform))
    top = _top_champions(riot.get_top_mastery(puuid, count=mastery_count, platform=platform))

    return {
        "riot_id": f"{account.get('gameName', game_name)}#{account.get('tagLine', tag_line)}",
        "game_name": account.get("gameName", game_name),
        "tag_line": account.get("tagLine", tag_line),
        "puuid": puuid,
        "summoner_level": summoner.get("summonerLevel"),
        "profile_icon_id": summoner.get("profileIconId"),
        "profile_icon_url": champions.profile_icon_url(summoner.get("profileIconId")),
        "ranked": ranked,
        "top_champions": top,
        "ddragon_version": champions.version(),
    }
