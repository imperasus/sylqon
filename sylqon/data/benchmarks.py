"""Rank-band × role performance benchmarks — the calibration table behind the
Players-tab gauges (CS/min pacing, aggression normalization, death baselines,
vision context).

Why this exists
---------------
The dashboard used to grade everyone against a single set of high-elo, farm-
focused constants (e.g. 8.5 CS/min for an ADC), which paints a Gold laner red
on essentially every game and turns the gauge into noise. Performance norms move
a lot with rank, so a benchmark is only meaningful *relative to the player's own
rank band*. This table encodes that: five bands × five roles, each with the
metrics the tab actually reads.

Provenance & regeneration
-------------------------
These values are **current-meta domain estimates** — a defensible starting point
that is already far more honest than one global constant. They are meant to be
**regenerated from real match data**: ``scripts/calibrate_benchmarks.py`` reads
the hosted ingestion service's ``match_participants`` + ``player_ranks`` (or the
aggregated ``computed_benchmarks``) and rewrites this file with measured
per-band, per-role percentiles. Until that job runs against a populated Postgres,
the estimates below stand in. Keep the *shape* stable so the regenerator can swap
values without touching call sites.

Metric definitions (per game, Summoner's Rift):
  cs_per_min      — a "keeping up?" target (≈60th percentile of the band/role)
  kills_assists   — typical K+A (kill participation proxy; aggression norm)
  deaths          — typical deaths (the baseline a tilt/int read compares to)
  vision_score    — typical vision score (map-control context)
"""
from __future__ import annotations

ROLES = ("top", "jungle", "middle", "bottom", "utility")

# Ordered low → high. Master/GM/Chall collapse into one apex band (their sample
# is thin and their norms are close). UNRANKED and anything unknown resolve to
# the middle band so an unranked scout still gets a sane, non-punishing target.
RANK_BANDS = ("iron_bronze", "silver_gold", "platinum_emerald", "diamond", "master_plus")
DEFAULT_BAND = "silver_gold"

_TIER_TO_BAND = {
    "IRON": "iron_bronze", "BRONZE": "iron_bronze",
    "SILVER": "silver_gold", "GOLD": "silver_gold",
    "PLATINUM": "platinum_emerald", "EMERALD": "platinum_emerald",
    "DIAMOND": "diamond",
    "MASTER": "master_plus", "GRANDMASTER": "master_plus", "CHALLENGER": "master_plus",
}

# BENCHMARKS[band][role] = {cs_per_min, kills_assists, deaths, vision_score}.
# CS/min gradients widen with rank (lower ranks farm markedly less); vision is
# strongly role-driven (support/jungle high) and rises with rank; deaths ease
# slightly as rank climbs. Supports are exempt from CS grading (low, flat bar).
BENCHMARKS: dict[str, dict[str, dict[str, float]]] = {
    "iron_bronze": {
        "top":     {"cs_per_min": 5.2, "kills_assists": 7.5,  "deaths": 6.4, "vision_score": 14},
        "jungle":  {"cs_per_min": 4.0, "kills_assists": 9.5,  "deaths": 6.6, "vision_score": 20},
        "middle":  {"cs_per_min": 5.5, "kills_assists": 8.5,  "deaths": 6.2, "vision_score": 15},
        "bottom":  {"cs_per_min": 5.8, "kills_assists": 8.5,  "deaths": 6.0, "vision_score": 14},
        "utility": {"cs_per_min": 0.8, "kills_assists": 11.5, "deaths": 6.8, "vision_score": 30},
    },
    "silver_gold": {
        "top":     {"cs_per_min": 5.9, "kills_assists": 7.8,  "deaths": 6.0, "vision_score": 16},
        "jungle":  {"cs_per_min": 4.6, "kills_assists": 10.0, "deaths": 6.2, "vision_score": 24},
        "middle":  {"cs_per_min": 6.3, "kills_assists": 9.0,  "deaths": 5.8, "vision_score": 17},
        "bottom":  {"cs_per_min": 6.6, "kills_assists": 9.0,  "deaths": 5.6, "vision_score": 16},
        "utility": {"cs_per_min": 1.0, "kills_assists": 12.5, "deaths": 6.4, "vision_score": 38},
    },
    "platinum_emerald": {
        "top":     {"cs_per_min": 6.6, "kills_assists": 8.0,  "deaths": 5.6, "vision_score": 18},
        "jungle":  {"cs_per_min": 5.1, "kills_assists": 10.5, "deaths": 5.8, "vision_score": 28},
        "middle":  {"cs_per_min": 7.1, "kills_assists": 9.3,  "deaths": 5.4, "vision_score": 19},
        "bottom":  {"cs_per_min": 7.4, "kills_assists": 9.3,  "deaths": 5.2, "vision_score": 18},
        "utility": {"cs_per_min": 1.2, "kills_assists": 13.0, "deaths": 6.0, "vision_score": 46},
    },
    "diamond": {
        "top":     {"cs_per_min": 7.2, "kills_assists": 8.2,  "deaths": 5.2, "vision_score": 20},
        "jungle":  {"cs_per_min": 5.6, "kills_assists": 11.0, "deaths": 5.5, "vision_score": 32},
        "middle":  {"cs_per_min": 7.7, "kills_assists": 9.6,  "deaths": 5.0, "vision_score": 21},
        "bottom":  {"cs_per_min": 8.0, "kills_assists": 9.6,  "deaths": 4.9, "vision_score": 20},
        "utility": {"cs_per_min": 1.4, "kills_assists": 13.5, "deaths": 5.7, "vision_score": 54},
    },
    "master_plus": {
        "top":     {"cs_per_min": 7.8, "kills_assists": 8.5,  "deaths": 4.9, "vision_score": 22},
        "jungle":  {"cs_per_min": 6.0, "kills_assists": 11.5, "deaths": 5.2, "vision_score": 36},
        "middle":  {"cs_per_min": 8.3, "kills_assists": 9.9,  "deaths": 4.7, "vision_score": 23},
        "bottom":  {"cs_per_min": 8.6, "kills_assists": 9.9,  "deaths": 4.6, "vision_score": 22},
        "utility": {"cs_per_min": 1.6, "kills_assists": 14.0, "deaths": 5.4, "vision_score": 62},
    },
}


def rank_band(tier: str | None) -> str:
    """Map a solo-queue tier to its benchmark band. Unknown/unranked → the middle
    band, so an unranked player gets a sane, non-punishing baseline."""
    return _TIER_TO_BAND.get(str(tier or "").upper(), DEFAULT_BAND)


def benchmark(role: str, tier: str | None = None) -> dict:
    """The full benchmark dict for a role at a tier's band. Falls back to the
    default band and, for an unknown role, to the middle-lane profile."""
    band = rank_band(tier)
    table = BENCHMARKS.get(band, BENCHMARKS[DEFAULT_BAND])
    return table.get(role) or table["middle"]


def cs_per_min_target(role: str, tier: str | None = None) -> float:
    """Rank-adaptive CS/min pacing target for the role."""
    return benchmark(role, tier)["cs_per_min"]


def as_dict() -> dict:
    """Serialize the table + mapping for the frontend (fetched once with the
    static data). Kept flat and JSON-safe."""
    return {
        "roles": list(ROLES),
        "bands": list(RANK_BANDS),
        "default_band": DEFAULT_BAND,
        "tier_to_band": dict(_TIER_TO_BAND),
        "table": BENCHMARKS,
    }
