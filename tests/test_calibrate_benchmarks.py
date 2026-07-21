"""Offline tests for the benchmark calibration core (scripts/calibrate_benchmarks).

Only the pure aggregation is covered — percentile maths, bucketing by rank band,
the sample-size floor and the emitted literal. The Postgres shell (``fetch_rows``)
needs a live database and is deliberately not exercised here.

Run: python -m pytest tests/test_calibrate_benchmarks.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import calibrate_benchmarks as cb


def _rows(n, tier, role, cs_per_min, kills=3, assists=5, deaths=5, vision=20):
    return [{"tier": tier, "role": role, "cs_per_min": cs_per_min, "kills": kills,
             "assists": assists, "deaths": deaths, "vision_score": vision}
            for _ in range(n)]


# ------------------------------------------------------------------ percentile
def test_percentile_endpoints_and_interpolation():
    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert cb.percentile(vals, 0.0) == 1.0
    assert cb.percentile(vals, 1.0) == 5.0
    assert cb.percentile(vals, 0.5) == 3.0
    assert cb.percentile([1.0, 2.0], 0.5) == 1.5   # interpolated


def test_percentile_single_value():
    assert cb.percentile([7.0], 0.6) == 7.0


def test_percentile_rejects_empty():
    import pytest
    with pytest.raises(ValueError):
        cb.percentile([], 0.5)


# ------------------------------------------------------------------- aggregate
def test_aggregate_buckets_by_rank_band():
    rows = _rows(300, "GOLD", "bottom", 6.5) + _rows(300, "CHALLENGER", "bottom", 8.6)
    table = cb.aggregate(rows, min_samples=200)
    assert table["silver_gold"]["bottom"]["cs_per_min"] == 6.5
    assert table["master_plus"]["bottom"]["cs_per_min"] == 8.6


def test_aggregate_drops_cells_below_the_sample_floor():
    table = cb.aggregate(_rows(50, "GOLD", "bottom", 6.5), min_samples=200)
    assert table == {}   # too thin → caller keeps the existing estimate


def test_aggregate_ignores_unknown_roles():
    table = cb.aggregate(_rows(300, "GOLD", "sidelane", 6.5), min_samples=200)
    assert table == {}


def test_aggregate_combines_kills_and_assists():
    rows = _rows(300, "GOLD", "middle", 6.0, kills=4, assists=6)
    table = cb.aggregate(rows, min_samples=200)
    assert table["silver_gold"]["middle"]["kills_assists"] == 10.0


def test_deaths_use_the_median_not_the_target_percentile():
    # Half the sample dies 2, half dies 10 → median 6, while a 0.6 percentile
    # would drift upward. Deaths are a baseline, not a target.
    rows = _rows(200, "GOLD", "top", 6.0, deaths=2) + _rows(200, "GOLD", "top", 6.0, deaths=10)
    table = cb.aggregate(rows, percentile_q=0.6, min_samples=200)
    assert table["silver_gold"]["top"]["deaths"] == 6.0


def test_unranked_rows_land_in_the_default_band():
    table = cb.aggregate(_rows(300, "UNRANKED", "top", 5.9), min_samples=200)
    assert "silver_gold" in table


# ---------------------------------------------------------------- render_table
def test_render_table_emits_valid_python_literal():
    rows = _rows(300, "GOLD", "bottom", 6.5) + _rows(300, "GOLD", "top", 5.9)
    text = cb.render_table(cb.aggregate(rows, min_samples=200))
    ns: dict = {}
    exec(text, ns)                       # must be syntactically valid
    table = ns["BENCHMARKS"]
    assert table["silver_gold"]["bottom"]["cs_per_min"] == 6.5
    # canonical role order preserved (top before bottom)
    assert list(table["silver_gold"]) == ["top", "bottom"]


def test_render_table_round_trips_the_shipped_shape():
    """The emitted literal must carry exactly the metrics benchmarks.py reads."""
    rows = _rows(300, "DIAMOND", "jungle", 5.6)
    ns: dict = {}
    exec(cb.render_table(cb.aggregate(rows, min_samples=200)), ns)
    row = ns["BENCHMARKS"]["diamond"]["jungle"]
    assert set(row) == {"cs_per_min", "kills_assists", "deaths", "vision_score"}
