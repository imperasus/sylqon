"""Normalized snapshot of the live game, parsed from the Live Client Data API.

Everything here comes from ``allgamedata`` — information already visible to the
player. ``LiveGameState.none()`` is the explicit "no game running" sentinel.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from sylqon.data import static

# Live Client Data API positions are upper-case (TOP/JUNGLE/MIDDLE/BOTTOM/UTILITY).
def _norm_role(position: str) -> str:
    p = (position or "").lower().strip()
    return static.ROLE_ALIASES.get(p, p)


@dataclass
class LiveGameState:
    active: bool
    game_time: float = 0.0          # seconds since game start
    my_name: str = ""
    champion: str = ""
    level: int = 0
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    cs: int = 0                     # creepScore (lane + jungle minions)
    cs_per_min: float = 0.0
    ward_score: float = 0.0
    role: str = ""                 # normalized top/jungle/middle/bottom/utility
    position: str = ""             # raw live position (may be empty)
    team: str = ""                 # ORDER | CHAOS
    is_dead: bool = False
    respawn_timer: float = 0.0
    objectives: dict = field(default_factory=dict)   # {dragons:{ally,enemy}, ...}
    death_times: list = field(default_factory=list)  # game-time of my deaths
    events: list = field(default_factory=list)       # lightweight event log
    roster: list = field(default_factory=list)       # all 10 players, live stats

    @classmethod
    def none(cls) -> "LiveGameState":
        return cls(active=False)

    def to_dict(self) -> dict:
        return asdict(self)


def _find_me(active: dict, all_players: list[dict]) -> dict | None:
    """Resolve the active player's row in ``allPlayers`` across the various name
    fields Riot has used (riotIdGameName / summonerName / riotId)."""
    candidates = set()
    for key in ("riotIdGameName", "summonerName", "riotId", "gameName"):
        v = (active.get(key) or "").strip()
        if v:
            candidates.add(v)
            candidates.add(v.split("#")[0])
    candidates.discard("")
    for p in all_players:
        for key in ("riotIdGameName", "summonerName", "riotId", "gameName"):
            v = (p.get(key) or "").strip()
            if v and (v in candidates or v.split("#")[0] in candidates):
                return p
    return None


def _team_map(all_players: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in all_players:
        team = p.get("team") or ""
        for key in ("riotIdGameName", "summonerName", "riotId", "gameName"):
            v = (p.get(key) or "").strip()
            if v:
                out[v] = team
                out[v.split("#")[0]] = team
    return out


def _parse_objectives(events: list[dict], name_to_team: dict[str, str],
                      my_team: str) -> dict:
    obj = {k: {"ally": 0, "enemy": 0} for k in ("dragons", "heralds", "barons", "towers")}
    kind = {"DragonKill": "dragons", "HeraldKill": "heralds", "BaronKill": "barons",
            "TurretKilled": "towers"}
    for e in events:
        key = kind.get(e.get("EventName", ""))
        if not key:
            continue
        if key == "towers":
            # Turret name encodes its OWNER side (T1 = ORDER, T2 = CHAOS). The team
            # that destroyed it is the other side.
            turret = e.get("TurretKilled", "")
            owner = "ORDER" if "_T1_" in turret else ("CHAOS" if "_T2_" in turret else "")
            if owner and my_team:
                obj[key]["ally" if owner != my_team else "enemy"] += 1
            continue
        kteam = name_to_team.get(e.get("KillerName", ""))
        if kteam and my_team:
            obj[key]["ally" if kteam == my_team else "enemy"] += 1
    return obj


def _player_name(p: dict) -> str:
    for key in ("riotIdGameName", "summonerName", "riotId", "gameName"):
        v = (p.get(key) or "").strip()
        if v:
            return v.split("#")[0]
    return ""


def _parse_roster(all_players: list[dict], my_team: str) -> list[dict]:
    """All ten players with their LIVE stats, tagged ally/enemy relative to me.
    Everything here is already on-screen in-game (Live Client Data ``allPlayers``)
    — champion, level, K/D/A, CS — so it is read-only and ToS-safe. Enemy *history*
    (puuid) is not exposed by Riot, so this is the live read, not a fingerprint."""
    out: list[dict] = []
    for p in all_players:
        scores = p.get("scores") or {}
        team = p.get("team") or ""
        out.append({
            "name": _player_name(p),
            "champion": p.get("championName") or "",
            "role": _norm_role(p.get("position") or ""),
            "team": team,
            "side": "ally" if (my_team and team == my_team) else "enemy",
            "kills": int(scores.get("kills") or 0),
            "deaths": int(scores.get("deaths") or 0),
            "assists": int(scores.get("assists") or 0),
            "cs": int(scores.get("creepScore") or 0),
            "level": int(p.get("level") or 0),
            "is_dead": bool(p.get("isDead")),
        })
    return out


def parse_live_state(raw: dict | None, *, my_role: str = "") -> LiveGameState:
    """Convert a raw ``allgamedata`` payload into a normalized snapshot. Returns
    the no-game sentinel for ``None``/malformed input. ``my_role`` (the champ-select
    role) is preferred over the live ``position`` field when provided."""
    if not isinstance(raw, dict):
        return LiveGameState.none()

    game = raw.get("gameData") or {}
    active = raw.get("activePlayer") or {}
    all_players = raw.get("allPlayers") or []
    events = (raw.get("events") or {}).get("Events") or []
    game_time = float(game.get("gameTime") or 0.0)

    me = _find_me(active, all_players) or {}
    scores = me.get("scores") or {}
    cs = int(scores.get("creepScore") or 0)
    cs_per_min = round(cs / (game_time / 60.0), 2) if game_time > 0 else 0.0
    my_team = me.get("team") or ""
    my_name = (me.get("riotIdGameName") or me.get("summonerName") or "").strip()

    position = me.get("position") or ""
    role = my_role or _norm_role(position)

    name_to_team = _team_map(all_players)
    objectives = _parse_objectives(events, name_to_team, my_team)
    death_times = [float(e.get("EventTime") or 0.0) for e in events
                   if e.get("EventName") == "ChampionKill" and e.get("VictimName") == my_name]
    light_events = [{"name": e.get("EventName"), "time": float(e.get("EventTime") or 0.0)}
                    for e in events]

    return LiveGameState(
        active=True,
        game_time=game_time,
        my_name=my_name,
        champion=me.get("championName") or active.get("championName") or "",
        level=int(me.get("level") or active.get("level") or 0),
        kills=int(scores.get("kills") or 0),
        deaths=int(scores.get("deaths") or 0),
        assists=int(scores.get("assists") or 0),
        cs=cs,
        cs_per_min=cs_per_min,
        ward_score=float(scores.get("wardScore") or 0.0),
        role=role,
        position=position,
        team=my_team,
        is_dead=bool(me.get("isDead")),
        respawn_timer=float(me.get("respawnTimer") or 0.0),
        objectives=objectives,
        death_times=death_times,
        events=light_events,
        roster=_parse_roster(all_players, my_team),
    )
