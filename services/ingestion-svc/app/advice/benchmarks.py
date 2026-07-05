"""Seed benchmark tables for the advice heuristics.

Numbers target the Iron–Gold audience (the bot's segment per the roadmap) and
are deliberately conservative medians, not pro targets. They are a *seed*: the
Phase 2 pool-svc aggregation replaces them with rank-band medians computed from
our own Match-V5 data. Every threshold can be overridden at runtime via
``ADVICE_TUNING_JSON`` (same pattern as the local app's MISSION_TUNING_JSON).
"""
from __future__ import annotations

import json
from pathlib import Path

from app import config

_DATA_DIR = Path(__file__).resolve().parent / "data"

# Completed (legendary-tier) item ids, generated from the repo's Data Dragon
# catalog (cache/ddragon_catalog.json): completed==true, gold >= 2000, and
# id < 100000 (6-digit ids are Arena-mode variants that never appear in SR
# timelines). Regenerate on patch bumps.
_completed = json.loads((_DATA_DIR / "completed_items.json").read_text(encoding="utf-8"))
CORE_ITEM_IDS: set[int] = {int(k) for k in _completed["core_items"]}
CORE_ITEM_NAMES: dict[int, str] = {
    int(k): v["name"] for k, v in _completed["core_items"].items()
}
CORE_ITEMS_PATCH: str = _completed["source_patch"]

CONTROL_WARD_ITEM_ID = 2055

# CS@minute medians per role (Iron–Gold blend). UTILITY is exempt from the CS
# heuristic entirely.
CS_BENCHMARKS: dict[str, dict[int, int]] = {
    "TOP": {10: 62, 15: 95},
    "JUNGLE": {10: 55, 15: 85},
    "MIDDLE": {10: 65, 15: 100},
    "BOTTOM": {10: 68, 15: 105},
}

# Wards placed per minute + control wards per game, per role.
VISION_BENCHMARKS: dict[str, dict[str, float]] = {
    "TOP": {"wards_per_min": 0.20, "control_wards": 1},
    "JUNGLE": {"wards_per_min": 0.45, "control_wards": 2},
    "MIDDLE": {"wards_per_min": 0.25, "control_wards": 1},
    "BOTTOM": {"wards_per_min": 0.25, "control_wards": 1},
    "UTILITY": {"wards_per_min": 0.70, "control_wards": 3},
}

_DEFAULT_TUNING: dict = {
    # death context
    "death_nearby_radius": 2500.0,      # units — "in the fight" radius
    "death_objective_radius": 5000.0,   # units — near a neutral objective
    "death_objective_window_ms": 30000,
    "death_ward_radius": 4000.0,        # a team ward this close counts as vision
    "death_ward_window_ms": 90000,
    "min_deaths_for_finding": 3,
    # cs
    "cs_deficit_pct_floor": 12.0,       # % below benchmark before it's a finding
    # item timing
    "first_core_minute": 15.0,
    "second_core_minute": 24.0,
    "dead_gold_threshold": 1500,
    "dead_gold_min_frames": 3,          # consecutive frames above threshold
    # vision
    "vision_deficit_pct_floor": 30.0,
    # objectives
    "objective_participation_floor": 0.5,
    "objective_radius": 4000.0,
    "min_team_objectives": 2,
}


def tuning() -> dict:
    """Defaults overlaid with ADVICE_TUNING_JSON."""
    merged = dict(_DEFAULT_TUNING)
    merged.update(config.ADVICE_TUNING)
    return merged
