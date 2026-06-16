"""Demo mode: a synthetic ``LiveGameState`` so the overlay + mission engine can
be exercised with no real game running.

``fake_live_state(elapsed_seconds, role)`` is a pure function of wall-clock
elapsed time. The in-game clock is accelerated (``SPEED``) and stats climb at a
steady pace with **no deaths**, so role missions complete in a quick demo loop
and points visibly accrue. Nothing here touches the real game client.
"""
from __future__ import annotations

from sylqon.livegame.state import LiveGameState

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
