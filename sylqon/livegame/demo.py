"""Demo mode: synthetic ``LiveGameState`` helpers for testing without a live game.

``fake_live_state(elapsed_seconds, role)`` is a pure function of wall-clock
elapsed time. The in-game clock is accelerated (``SPEED``) and stats climb at a
steady pace with **no deaths**, so role missions complete in a quick demo loop
and points visibly accrue. Nothing here touches the real game client.

``match_to_live_state(match, my_puuid)`` converts a real MATCH-V5 response into
a static end-of-game snapshot so the PlayersView live panel can be populated from
match history without a running game.
"""
from __future__ import annotations

from sylqon.data import static
from sylqon.livegame.state import LiveGameState, _infer_roles

SPEED = 10.0         # in-game seconds per real second (fast-forward for testing)
CS_PER_MIN = 14.0    # high enough that the farm missions complete in-window
WARD_PER_MIN = 5.0
TAKEDOWN_EVERY = 40  # game-seconds between scripted takedowns
DRAGON_AT = 60       # game-seconds when an ally dragon lands
DEMO_CHAMPION = {"bottom": "Jinx", "middle": "Ahri", "top": "Garen",
                 "jungle": "Lee Sin", "utility": "Lulu"}


def fake_live_state(elapsed_seconds: float, role: str = "bottom") -> LiveGameState:
    role = role or "bottom"
    gt = max(0.0, elapsed_seconds * SPEED)            # accelerated game time
    minutes = gt / 60.0
    cs = int(minutes * CS_PER_MIN)
    ward = round(minutes * WARD_PER_MIN, 1)
    takedowns = int(gt // TAKEDOWN_EVERY)              # scripted takedowns
    kills = takedowns // 2
    assists = takedowns - kills
    dragons_ally = 1 if gt >= DRAGON_AT else 0
    return LiveGameState(
        active=True,
        game_time=round(gt, 1),
        my_name="Demo Summoner",
        champion=DEMO_CHAMPION.get(role, "Jinx"),
        level=min(18, 1 + int(gt // 90)),
        kills=kills, deaths=0, assists=assists,
        cs=cs,
        cs_per_min=round(cs / minutes, 1) if minutes > 0 else 0.0,
        ward_score=ward,
        role=role,
        position=role.upper(),
        team="ORDER",
        is_dead=False,
        respawn_timer=0.0,
        objectives={"dragons": {"ally": dragons_ally, "enemy": 0},
                    "heralds": {"ally": 0, "enemy": 0},
                    "barons": {"ally": 0, "enemy": 0},
                    "towers": {"ally": 0, "enemy": 0}},
        death_times=[],
        events=[],
    )


def match_to_live_state(match: dict, my_puuid: str) -> LiveGameState:
    """Convert a MATCH-V5 payload into a static end-of-game LiveGameState.
    The roster is fully populated so the PlayersView live panel shows all 10
    players with their final K/D/A, CS, champion and level."""
    info = match.get("info") or {}
    participants = info.get("participants") or []

    me = next((p for p in participants if p.get("puuid") == my_puuid), None)
    if not me:
        return LiveGameState.none()

    game_duration = float(info.get("gameDuration") or 0)
    if game_duration > 100_000:
        game_duration = game_duration / 1000.0
    minutes = game_duration / 60.0 if game_duration > 0 else 1.0

    my_team_id = me.get("teamId", 100)
    my_team = "ORDER" if my_team_id == 100 else "CHAOS"

    roster: list[dict] = []
    for p in participants:
        team_id = p.get("teamId", 100)
        team = "ORDER" if team_id == 100 else "CHAOS"
        pos = (p.get("teamPosition") or p.get("individualPosition") or "").lower()
        cs = (p.get("totalMinionsKilled") or 0) + (p.get("neutralMinionsKilled") or 0)
        roster.append({
            "name": p.get("riotIdGameName") or p.get("summonerName") or "",
            "champion": p.get("championName") or "",
            "role": static.ROLE_ALIASES.get(pos, pos),
            "team": team,
            "side": "ally" if team == my_team else "enemy",
            "kills": int(p.get("kills") or 0),
            "deaths": int(p.get("deaths") or 0),
            "assists": int(p.get("assists") or 0),
            "cs": int(cs),
            "level": int(p.get("champLevel") or 0),
            "is_dead": False,
        })
    _infer_roles(roster)

    me_cs = (me.get("totalMinionsKilled") or 0) + (me.get("neutralMinionsKilled") or 0)
    me_pos = (me.get("teamPosition") or me.get("individualPosition") or "").lower()
    me_role = static.ROLE_ALIASES.get(me_pos, me_pos) or "bottom"

    return LiveGameState(
        active=True,
        game_time=game_duration,
        my_name=me.get("riotIdGameName") or me.get("summonerName") or "",
        champion=me.get("championName") or "",
        level=int(me.get("champLevel") or 0),
        kills=int(me.get("kills") or 0),
        deaths=int(me.get("deaths") or 0),
        assists=int(me.get("assists") or 0),
        cs=int(me_cs),
        cs_per_min=round(me_cs / minutes, 2),
        ward_score=float(me.get("visionScore") or 0),
        role=me_role,
        position=me.get("teamPosition") or "",
        team=my_team,
        is_dead=False,
        respawn_timer=0.0,
        objectives={},
        death_times=[],
        events=[],
        roster=roster,
    )
