"""Shared statistics for the matchup selectors (core / rune page / spells).

The selectors deviate from the meta option only for COVERAGE reasons (a
challenger answers a mandated counter tag the meta misses); win rate is a
sanity brake, not the objective. Raw win-rate deltas are noise at small
samples, so the brake is Wilson-interval based: a challenger is only rejected
as "worse" when its interval sits confidently below the meta option's —
statistically indistinguishable options stay eligible regardless of sample
size (the play/share floors handle degenerate samples).
"""
from __future__ import annotations

import math

Z_95 = 1.96


def wilson_interval(wins: float, games: int, z: float = Z_95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion. ``games <= 0`` returns
    the maximally uninformative (0, 1)."""
    if games <= 0:
        return 0.0, 1.0
    p = max(0.0, min(1.0, wins / games))
    denom = 1 + z * z / games
    centre = p + z * z / (2 * games)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * games)) / games)
    return (centre - margin) / denom, (centre + margin) / denom


def confidently_worse(challenger_wr: float, challenger_games: int,
                      meta_wr: float, meta_games: int, z: float = Z_95) -> bool:
    """True when the challenger's win-rate interval lies entirely below the
    meta option's — the only case where win rate alone should veto a
    coverage-justified swap."""
    if challenger_games <= 0 or meta_games <= 0:
        return False
    _, ch_high = wilson_interval(challenger_wr * challenger_games,
                                 challenger_games, z)
    meta_low, _ = wilson_interval(meta_wr * meta_games, meta_games, z)
    return ch_high < meta_low


def adaptive_floor(total_games: int, cap: int = 20, floor: int = 8,
                   fraction: float = 0.10) -> int:
    """Minimum sample for a challenger, adaptive to the data source's scale:
    op.gg pages carry thousands of games (floor caps at ``cap``), the hosted
    service aggregates a few dozen (floor relaxes toward ``floor``)."""
    return max(floor, min(cap, int(total_games * fraction)))
