"""Team power-curve (tempo vs scaling) read for the draft board.

The single most important draft axis the engine was missing: *when* does each
team come online. A comp of lane bullies and early junglers wins if the game is
forced early; a comp of hypercarries and scaling tanks wins if it reaches three
items. Knowing which side you are on dictates the entire macro plan, yet nothing
in the draft read expressed it.

This module assigns every champion an ``{early, mid, late}`` power distribution
(from class tags, refined by the curated threat lists this repo already keeps),
aggregates each team, and produces a single actionable read: who out-scales, who
out-tempos, and what that means for the game plan. Pure and network-free, like
:mod:`sylqon.analysis.draft_intel`; accepts ``ChampPick`` instances or the plain
``{"name", "tags"}`` dict shape.
"""
from __future__ import annotations

from sylqon.data import static

# Class → base power distribution (early, mid, late), summing to 1.0. The class
# is the coarse prior; the curated overrides below refine the real outliers.
_BASE = {
    "Marksman": (0.20, 0.30, 0.50),   # scale with items → late
    "Mage": (0.28, 0.42, 0.30),       # item-spike mid
    "Assassin": (0.32, 0.48, 0.20),   # 1-2 item mid spike, fall off late
    "Fighter": (0.42, 0.38, 0.20),    # strong laning, taper
    "Tank": (0.26, 0.40, 0.34),       # scale with team/resists
    "Support": (0.32, 0.40, 0.28),
}
_CLASS_PRIORITY = ("Marksman", "Assassin", "Mage", "Fighter", "Tank", "Support")

# Curated outliers — champions whose real curve diverges from their class prior.
_HARD_LATE = {
    "Kayle", "Kassadin", "Vayne", "Jax", "Nasus", "Vladimir", "Veigar", "Azir",
    "Aurelion Sol", "Twitch", "Kog'Maw", "Smolder", "Senna", "Ryze", "Gangplank",
    "Cassiopeia", "Viktor", "Kindred", "Sion", "Ornn",
}
_HARD_EARLY = {
    "Draven", "Lucian", "Renekton", "Pantheon", "Lee Sin", "Elise", "Nidalee",
    "Pyke", "Kled", "Xin Zhao", "Olaf", "Tryndamere", "Skarner",
}


def _name(p) -> str:
    return p["name"] if isinstance(p, dict) else p.name


def _tags(p) -> set:
    return set(p["tags"] if isinstance(p, dict) else p.tags)


def _primary_class(tags: set) -> str:
    for cls in _CLASS_PRIORITY:
        if cls in tags:
            return cls
    return ""


def _normalize(e: float, m: float, l: float) -> dict:
    e, m, l = max(0.0, e), max(0.0, m), max(0.0, l)
    total = e + m + l or 1.0
    return {"early": e / total, "mid": m / total, "late": l / total}


def champion_curve(name: str, tags: set) -> dict:
    """``{early, mid, late}`` (sums to 1.0) for one champion."""
    e, m, l = _BASE.get(_primary_class(tags), (0.34, 0.36, 0.30))
    if name in _HARD_LATE or name in static.SPLIT_PUSH_CHAMPS:
        e, m, l = e - 0.15, m - 0.08, l + 0.23
    if name in _HARD_EARLY or name in static.IGNITE_KILL_LANERS:
        e, m, l = e + 0.20, m - 0.06, l - 0.14
    if name in static.HEAVY_POKE:
        m += 0.08                       # poke comps peak in the mid-game siege
    if name in static.HEAVY_TANK:
        l += 0.10                       # tanks scale with resists/team
    return _normalize(e, m, l)


def team_curve(picks: list) -> dict:
    """Mean ``{early, mid, late}`` across a team's revealed picks (empty picks
    ignored). Returns a flat neutral curve when nothing is revealed."""
    picks = [p for p in picks if p]
    if not picks:
        return {"early": 1 / 3, "mid": 1 / 3, "late": 1 / 3}
    curves = [champion_curve(_name(p), _tags(p)) for p in picks]
    n = len(curves)
    return {phase: sum(c[phase] for c in curves) / n
            for phase in ("early", "mid", "late")}


def _scaling_index(curve: dict) -> float:
    """Late minus early: positive = a scaling comp, negative = a tempo comp."""
    return curve["late"] - curve["early"]


# Minimum scaling-index gap before we call the matchup lopsided rather than even.
_TEMPO_EDGE = 0.06


def tempo_read(ally_picks: list, enemy_picks: list) -> dict:
    """Compare the two teams' power curves into one actionable read.

    Returns ``{label, detail, sign, ally_index, enemy_index, phase}`` where
    ``sign`` is +1 when YOU want to play for the late game, -1 when you want to
    force it early, 0 when the curves are even. ``phase`` names the window you
    should aim the game at."""
    a, e = team_curve(ally_picks), team_curve(enemy_picks)
    ai, ei = _scaling_index(a), _scaling_index(e)
    diff = ai - ei  # >0: you scale harder than them

    if diff >= _TEMPO_EDGE:
        label, sign, phase = "You out-scale", 1, "late"
        detail = ("Your comp powers up later — trade early skirmishes for scaling, "
                  "give up nothing for free and let the game go long.")
    elif diff <= -_TEMPO_EDGE:
        label, sign, phase = "You out-tempo", -1, "early"
        detail = ("Your comp spikes earlier — force fights and objectives before "
                  "2-3 items, close the game before they come online.")
    else:
        label, sign, phase = "Even power curves", 0, "mid"
        detail = ("Neither side has a clear timing edge — win the mid-game on "
                  "picks and objective setups.")

    return {"label": label, "detail": detail, "sign": sign, "phase": phase,
            "ally_index": round(ai, 2), "enemy_index": round(ei, 2)}
