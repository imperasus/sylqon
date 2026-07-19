"""Offline tests for the shared selector statistics (analysis/select_util.py):
the Wilson interval, the confidently-worse win-rate veto, and the adaptive
sample floor.

Run: python -m pytest tests/test_select_util.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon.analysis.select_util import (
    adaptive_floor,
    confidently_worse,
    wilson_interval,
)


class TestWilsonInterval:
    def test_bounds_ordered_and_contain_point(self):
        lo, hi = wilson_interval(55, 100)
        assert 0.0 <= lo < 0.55 < hi <= 1.0

    def test_zero_games_is_maximally_uncertain(self):
        assert wilson_interval(0, 0) == (0.0, 1.0)

    def test_larger_sample_narrows_interval(self):
        small = wilson_interval(6, 10)
        large = wilson_interval(600, 1000)
        assert (small[1] - small[0]) > (large[1] - large[0])


class TestConfidentlyWorse:
    def test_clear_gap_is_worse(self):
        # 40% over 130 games vs 55% over 1900 — intervals don't overlap.
        assert confidently_worse(0.40, 130, 0.55, 1900)

    def test_small_dip_not_confidently_worse(self):
        # 53% over 120 vs 56% over 1900 — overlapping intervals → not a veto.
        assert not confidently_worse(0.53, 120, 0.56, 1900)

    def test_higher_winrate_never_worse(self):
        assert not confidently_worse(0.60, 200, 0.55, 1900)

    def test_missing_samples_never_veto(self):
        assert not confidently_worse(0.10, 0, 0.55, 1900)
        assert not confidently_worse(0.10, 200, 0.55, 0)


class TestAdaptiveFloor:
    def test_opgg_scale_caps_at_cap(self):
        assert adaptive_floor(50_000, cap=20, floor=8) == 20

    def test_service_scale_relaxes_to_fraction(self):
        # 90 total games → 10% = 9, above floor, below cap.
        assert adaptive_floor(90, cap=20, floor=8) == 9

    def test_tiny_sample_hits_floor(self):
        assert adaptive_floor(30, cap=20, floor=8) == 8


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
