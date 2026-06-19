"""Pre-game lobby scouting.

For every lobby/champ-select player whose identity we can resolve (a ``puuid``;
ranked solo anonymizes enemies, so this is realistically the premade lobby plus
visible allies), we pull their recent Summoner's Rift games via the LCU and
distil a **playstyle fingerprint**: main role, champion pool, how aggressive
they play, their comfort/one-trick champion, recent form, and a few descriptive
tags.

This module is deliberately **catalog-free and id-based** (mirroring
``history.py``): it returns ``championId`` keys, and the runtime resolves them
to names/slugs against the catalog when it publishes scout state. That keeps the
fingerprint logic pure and unit-testable without a loaded catalog.

Everything degrades to ``None`` / empty on missing data so the dashboard simply
omits the scout for an unresolved player. READ-ONLY: GET match history only.
"""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import asdict, dataclass, field

from sylqon.lcu.client import LCUClient
from sylqon.lcu.history import _fetch_games, normalize_game, puuid_matches_path

log = logging.getLogger(__name__)

# How many recent games define "recent form".
RECENT_WINDOW = 10
# Top-N champions surfaced in the pool.
POOL_SIZE = 5

# Playstyle thresholds (per-game averages over the analyzed SR games). Kept as
# module constants so they're easy to tune and assert against in tests.
AGGRO_KILLS = 6.0          # avg kills at/above this → fights for kills
AGGRO_DEATHS = 6.5         # avg deaths at/above this → high-risk / dies a lot
FARM_CS_PER_MIN = 7.0      # avg CS/min at/above this → farm-focused
PLAYMAKER_ASSISTS = 10.0   # avg assists at/above this → enables teammates
ONE_TRICK_SHARE = 0.5      # one champ ≥ this share of games → one-trick


@dataclass
class PlayerFingerprint:
    """A compact, id-based read of how a player plays. ``None``-equivalent is an
    empty fingerprint with ``games_analyzed == 0``."""
    games_analyzed: int = 0
    main_role: str = ""
    roles: dict = field(default_factory=dict)            # role -> game count
    champion_pool: list = field(default_factory=list)    # [{champion_id, games, wins, win_rate}]
    comfort: dict | None = None                          # {champion_id, games, share}
    aggression: float = 0.0                              # 0..1 normalized
    avg_kda: dict = field(default_factory=dict)          # {kills, deaths, assists, ratio}
    avg_cs_per_min: float = 0.0
    recent_form: dict = field(default_factory=dict)      # {games, wins, win_rate, streak}
    playstyle_tags: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def recent_games_for_puuid(client: LCUClient, puuid: str,
                           count: int = 40) -> list[dict]:
    """Newest-first normalized SR games for an arbitrary player by puuid.
    Returns ``[]`` when the history is hidden/unavailable (e.g. anonymized)."""
    if not puuid:
        return []
    games = _fetch_games(client, count, path=puuid_matches_path(puuid))
    games.sort(key=lambda g: g.get("gameCreation", 0), reverse=True)
    out: list[dict] = []
    for g in games:
        normalized = normalize_game(g)
        if normalized is not None:
            out.append(normalized)
    return out


def fingerprint(games: list[dict]) -> PlayerFingerprint:
    """Distil a playstyle fingerprint from normalized SR games (newest first).
    Empty input yields an empty fingerprint."""
    if not games:
        return PlayerFingerprint()

    n = len(games)
    roles = Counter(g["role"] for g in games if g.get("role"))
    main_role = roles.most_common(1)[0][0] if roles else ""

    pool = _champion_pool(games)
    comfort = _comfort(pool, n)
    avg_kda = _avg_kda(games)
    avg_cs = round(sum(g["stats"].get("cs_per_min", 0.0) for g in games) / n, 2)
    aggression = _aggression_score(avg_kda, avg_cs)
    tags = _playstyle_tags(avg_kda, avg_cs, comfort)
    recent = _recent_form(games[:RECENT_WINDOW])

    return PlayerFingerprint(
        games_analyzed=n,
        main_role=main_role,
        roles=dict(roles),
        champion_pool=pool[:POOL_SIZE],
        comfort=comfort,
        aggression=aggression,
        avg_kda=avg_kda,
        avg_cs_per_min=avg_cs,
        recent_form=recent,
        playstyle_tags=tags,
    )


# ----------------------------------------------------------------- internals
def _champion_pool(games: list[dict]) -> list[dict]:
    """Per-champion games/wins/win-rate, most-played first."""
    by_champ: dict[int, dict] = {}
    for g in games:
        cid = g["champion_id"]
        bucket = by_champ.setdefault(cid, {"champion_id": cid, "games": 0, "wins": 0})
        bucket["games"] += 1
        if g.get("result") == "Win":
            bucket["wins"] += 1
    pool = list(by_champ.values())
    for b in pool:
        b["win_rate"] = round(b["wins"] / b["games"], 3) if b["games"] else 0.0
    pool.sort(key=lambda b: (b["games"], b["win_rate"]), reverse=True)
    return pool


def _comfort(pool: list[dict], total_games: int) -> dict | None:
    """The most-played champion and how dominant it is in the sample."""
    if not pool or not total_games:
        return None
    top = pool[0]
    return {
        "champion_id": top["champion_id"],
        "games": top["games"],
        "win_rate": top["win_rate"],
        "share": round(top["games"] / total_games, 3),
    }


def _avg_kda(games: list[dict]) -> dict:
    n = len(games)
    k = sum(g["kda"].get("kills", 0) for g in games) / n
    d = sum(g["kda"].get("deaths", 0) for g in games) / n
    a = sum(g["kda"].get("assists", 0) for g in games) / n
    ratio = (k + a) / d if d else (k + a)
    return {"kills": round(k, 1), "deaths": round(d, 1),
            "assists": round(a, 1), "ratio": round(ratio, 2)}


def _aggression_score(avg_kda: dict, avg_cs: float) -> float:
    """0..1 blend of kill involvement and risk-taking. High kills+assists and
    high deaths read as aggressive; low deaths and high farm read as passive."""
    kills = avg_kda.get("kills", 0.0)
    deaths = avg_kda.get("deaths", 0.0)
    assists = avg_kda.get("assists", 0.0)
    involvement = min((kills + assists) / 18.0, 1.0)   # ~18 K+A → maxed
    risk = min(deaths / 9.0, 1.0)                       # ~9 deaths → maxed
    farm_penalty = min(avg_cs / FARM_CS_PER_MIN, 1.0) * 0.2
    score = 0.6 * involvement + 0.4 * risk - farm_penalty
    return round(max(0.0, min(score, 1.0)), 2)


def _playstyle_tags(avg_kda: dict, avg_cs: float,
                    comfort: dict | None) -> list[str]:
    tags: list[str] = []
    kills = avg_kda.get("kills", 0.0)
    deaths = avg_kda.get("deaths", 0.0)
    assists = avg_kda.get("assists", 0.0)
    if kills >= AGGRO_KILLS and deaths >= AGGRO_DEATHS:
        tags.append("aggressive")
    elif deaths <= AGGRO_DEATHS - 2.5 and avg_kda.get("ratio", 0.0) >= 2.5:
        tags.append("calculated")
    if avg_cs >= FARM_CS_PER_MIN:
        tags.append("farm-focused")
    if assists >= PLAYMAKER_ASSISTS and assists >= kills:
        tags.append("playmaker")
    if kills >= AGGRO_KILLS and avg_kda.get("ratio", 0.0) >= 3.0:
        tags.append("carry-threat")
    if comfort and comfort.get("share", 0.0) >= ONE_TRICK_SHARE:
        tags.append("one-trick")
    return tags


def _recent_form(games: list[dict]) -> dict:
    """Win rate over the recent window plus the current win/loss streak."""
    if not games:
        return {"games": 0, "wins": 0, "win_rate": 0.0, "streak": 0}
    wins = sum(1 for g in games if g.get("result") == "Win")
    # Streak: signed run length from the most recent game (+win / -loss).
    first_win = games[0].get("result") == "Win"
    streak = 0
    for g in games:
        if (g.get("result") == "Win") == first_win:
            streak += 1
        else:
            break
    return {
        "games": len(games),
        "wins": wins,
        "win_rate": round(wins / len(games), 3),
        "streak": streak if first_win else -streak,
    }
