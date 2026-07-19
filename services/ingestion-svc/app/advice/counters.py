"""Counter-item coverage heuristic — the post-game half of the closed loop.

The draft-time loadout coach (in the local Sylqon app) recommends counter items
against the enemy comp: anti-heal into healing, %penetration into a stacked
frontline. This heuristic checks, from the Match-V5 data, whether the player
actually BOUGHT that counter — so the same rule that shaped the draft advice is
verified against how the game was really played.

Standalone (the service must not import sylqon): the small counter-item id set
and the enemy-threat champion sets live here, mirroring
``sylqon/data/static.py`` but maintained independently for the service.
"""
from __future__ import annotations

from app.advice.heuristics import Finding, PlayerContext
from app.advice.timeline import TimelineView

# Completed items that apply Grievous Wounds (anti-heal).
ANTI_HEAL_ITEM_IDS: frozenset[int] = frozenset({
    3033,   # Mortal Reminder
    3165,   # Morellonomicon
    6609,   # Chempunk Chainsword
    3075,   # Thornmail
    3123,   # Executioner's Calling (component — counts: the cut is what matters)
    3916,   # Oblivion Orb (component)
})

# Completed items that carry meaningful % armor / magic penetration (vs tanks).
PERCENT_PEN_ITEM_IDS: frozenset[int] = frozenset({
    3036,   # Lord Dominik's Regards
    6694,   # Serylda's Grudge
    3135,   # Void Staff
    3137,   # Cryptbloom
    3071,   # Black Cleaver
    3033,   # Mortal Reminder (also % pen)
})

# Champions whose kit provides heavy sustain the enemy must cut. Kept in sync
# with sylqon/data/static.py HEAVY_HEALING by hand (service is standalone).
HEALING_CHAMPIONS: frozenset[str] = frozenset({
    "Soraka", "Aatrox", "DrMundo", "Dr. Mundo", "Vladimir", "Sylas", "Swain",
    "Yuumi", "Sona", "Nami", "Warwick", "Fiora", "Illaoi", "Briar", "Zac",
    "Maokai", "Kayn", "Olaf", "Trundle",
})

# High-HP frontline champions whose stacked resists demand penetration.
TANK_CHAMPIONS: frozenset[str] = frozenset({
    "Ornn", "Sion", "Malphite", "Rammus", "Zac", "Sejuani", "Chogath",
    "Cho'Gath", "DrMundo", "Dr. Mundo", "TahmKench", "Tahm Kench", "Shen",
    "KSante", "K'Sante", "Maokai", "Amumu", "Leona", "Nautilus", "Poppy",
})

# The counter heuristic only applies to damage-dealing roles; an enchanter or
# tank support that skips anti-heal is not making the same mistake.
_DAMAGE_ROLES = {"TOP", "JUNGLE", "MIDDLE", "BOTTOM"}


def _norm(name: str) -> str:
    return (name or "").replace(" ", "").replace("'", "").replace(".", "")


def counter_item_coverage(view: TimelineView, ctx: PlayerContext,
                          tun: dict) -> Finding | None:
    """Missing counter item vs a comp that clearly demanded it. Fires at most
    one finding (anti-heal takes priority over %pen), only for damage roles and
    only once the game ran long enough to have completed the counter."""
    enemies = getattr(ctx, "enemy_champions", ()) or ()
    if not enemies or ctx.team_position not in _DAMAGE_ROLES:
        return None
    game_min = view.game_length_ms() / 60000
    if game_min < tun.get("counter_min_game_min", 22.0):
        return None

    purchased = {e.get("itemId") for e in view.item_purchases()}
    enemy_norm = {_norm(c) for c in enemies}

    healers = [c for c in enemies if _norm(c) in {_norm(h) for h in HEALING_CHAMPIONS}]
    if len(healers) >= tun.get("counter_healing_min", 2) \
            and not (purchased & ANTI_HEAL_ITEM_IDS):
        return Finding(
            type="counter_coverage",
            severity=70,
            message_key="counter_no_antiheal",
            evidence={"healers": len(healers),
                      "enemies": ", ".join(sorted(set(healers)))},
        )

    tanks = [c for c in enemies if _norm(c) in {_norm(t) for t in TANK_CHAMPIONS}]
    if len(tanks) >= tun.get("counter_tank_min", 2) \
            and not (purchased & PERCENT_PEN_ITEM_IDS):
        return Finding(
            type="counter_coverage",
            severity=55,
            message_key="counter_no_pen",
            evidence={"tanks": len(tanks),
                      "enemies": ", ".join(sorted(set(tanks)))},
        )

    _ = enemy_norm  # reserved for future per-threat checks
    return None
