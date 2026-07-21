"""Regenerate the rank-band × role benchmark table from real match data.

``sylqon/data/benchmarks.py`` ships with current-meta *estimates*. This script
replaces them with measured percentiles from the hosted ingestion service's
Postgres (``match_participants`` joined to ``player_ranks`` for the rank band).

    # with the ingestion-svc Postgres reachable:
    python scripts/calibrate_benchmarks.py --dsn postgresql://user:pw@host:5433/sylqon

It prints the ``BENCHMARKS`` literal to stdout; paste it into
``sylqon/data/benchmarks.py`` (the surrounding docstring and accessors are
hand-maintained, so nothing else needs to change).

The aggregation itself (:func:`aggregate`, :func:`render_table`) is pure and
unit-tested offline against synthetic rows — only :func:`fetch_rows` needs a
live database.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon.data.benchmarks import RANK_BANDS, ROLES, rank_band

# A "keeping up?" bar should sit a little above the median — matching the shipped
# table's framing. 0.5 would mark half the band as failing by construction.
TARGET_PERCENTILE = 0.60
# Below this many samples a (band, role) cell is too thin to trust; the caller
# keeps the previous/estimated value rather than shipping noise.
MIN_SAMPLES = 200

_METRICS = ("cs_per_min", "kills_assists", "deaths", "vision_score")


def percentile(values: list[float], q: float) -> float:
    """Linear-interpolated percentile of an unsorted list. ``q`` in [0, 1]."""
    if not values:
        raise ValueError("percentile of an empty sample")
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    pos = q * (len(ordered) - 1)
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    frac = pos - low
    return float(ordered[low] * (1 - frac) + ordered[high] * frac)


def aggregate(rows, percentile_q: float = TARGET_PERCENTILE,
              min_samples: int = MIN_SAMPLES) -> dict:
    """Build ``{band: {role: {metric: value}}}`` from participant rows.

    Each row is a mapping with ``tier``, ``role`` and the raw per-game metrics
    (``cs_per_min``, ``kills``, ``assists``, ``deaths``, ``vision_score``).
    Cells below ``min_samples`` are omitted so the caller can keep the previous
    value instead of shipping a noisy one. Deaths use the *median* (a central
    baseline, not a target); the rest use ``percentile_q``.
    """
    buckets: dict[tuple[str, str], dict[str, list[float]]] = {}
    for row in rows:
        role = str(row.get("role") or "").lower()
        if role not in ROLES:
            continue
        band = rank_band(row.get("tier"))
        cell = buckets.setdefault((band, role), {m: [] for m in _METRICS})
        cell["cs_per_min"].append(float(row.get("cs_per_min") or 0.0))
        cell["kills_assists"].append(
            float(row.get("kills") or 0) + float(row.get("assists") or 0))
        cell["deaths"].append(float(row.get("deaths") or 0))
        cell["vision_score"].append(float(row.get("vision_score") or 0))

    table: dict[str, dict[str, dict[str, float]]] = {}
    for (band, role), cell in buckets.items():
        if len(cell["cs_per_min"]) < min_samples:
            continue
        table.setdefault(band, {})[role] = {
            "cs_per_min": round(percentile(cell["cs_per_min"], percentile_q), 1),
            "kills_assists": round(percentile(cell["kills_assists"], percentile_q), 1),
            # A baseline to compare against, so the middle of the distribution.
            "deaths": round(percentile(cell["deaths"], 0.5), 1),
            "vision_score": round(percentile(cell["vision_score"], percentile_q)),
        }
    return table


def render_table(table: dict) -> str:
    """Render the aggregated table as the ``BENCHMARKS`` Python literal, in the
    canonical band/role order so diffs stay readable."""
    lines = ["BENCHMARKS: dict[str, dict[str, dict[str, float]]] = {"]
    for band in RANK_BANDS:
        roles = table.get(band)
        if not roles:
            continue
        lines.append(f'    "{band}": {{')
        for role in ROLES:
            row = roles.get(role)
            if not row:
                continue
            lines.append(
                f'        "{role}":'.ljust(20)
                + f' {{"cs_per_min": {row["cs_per_min"]}, '
                  f'"kills_assists": {row["kills_assists"]}, '
                  f'"deaths": {row["deaths"]}, '
                  f'"vision_score": {int(row["vision_score"])}}},'
            )
        lines.append("    },")
    lines.append("}")
    return "\n".join(lines)


# --------------------------------------------------------------------- I/O shell
_QUERY = """
SELECT COALESCE(pr.tier, 'UNRANKED')                       AS tier,
       LOWER(mp.team_position)                             AS role,
       mp.total_minions_killed + mp.neutral_minions_killed AS cs,
       m.game_duration                                     AS duration,
       mp.kills, mp.assists, mp.deaths, mp.vision_score
  FROM match_participants mp
  JOIN matches m       ON m.match_id = mp.match_id
  LEFT JOIN player_ranks pr ON pr.puuid = mp.puuid
 WHERE m.game_duration >= %s
   AND mp.team_position IS NOT NULL AND mp.team_position <> ''
 LIMIT %s
"""


def fetch_rows(dsn: str, min_duration_s: int = 960, limit: int = 400_000):
    """Stream participant rows from the ingestion-svc Postgres. Remakes and
    early surrenders are excluded — they wreck per-minute medians."""
    import psycopg  # imported lazily: only the live path needs the driver

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(_QUERY, (min_duration_s, limit))
        for tier, role, cs, duration, kills, assists, deaths, vision in cur:
            minutes = (duration or 0) / 60.0
            if minutes <= 0:
                continue
            yield {"tier": tier, "role": role, "cs_per_min": (cs or 0) / minutes,
                   "kills": kills, "assists": assists, "deaths": deaths,
                   "vision_score": vision}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dsn", required=True, help="ingestion-svc Postgres DSN")
    ap.add_argument("--percentile", type=float, default=TARGET_PERCENTILE)
    ap.add_argument("--min-samples", type=int, default=MIN_SAMPLES)
    args = ap.parse_args()

    table = aggregate(fetch_rows(args.dsn), args.percentile, args.min_samples)
    if not table:
        print("No (band, role) cell cleared the sample floor — nothing to emit.",
              file=sys.stderr)
        return 1
    missing = [f"{b}/{r}" for b in RANK_BANDS for r in ROLES
               if r not in table.get(b, {})]
    if missing:
        print(f"# NOTE: thin sample, keep the existing estimate for: {', '.join(missing)}",
              file=sys.stderr)
    print(render_table(table))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
