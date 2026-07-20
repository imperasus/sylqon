"""F6 — calibratable win-probability model + evaluation harness."""
from __future__ import annotations

from sylqon.analysis import win_model


# -- production mapping ------------------------------------------------------
def test_edge_zero_is_even():
    assert win_model.edge_to_win_pct(0.0) == 50


def test_monotonic_and_bounded():
    assert win_model.edge_to_win_pct(-5) < win_model.edge_to_win_pct(0) \
        < win_model.edge_to_win_pct(5)
    assert win_model.edge_to_win_pct(1000) <= win_model.WIN_PCT_CEIL
    assert win_model.edge_to_win_pct(-1000) >= win_model.WIN_PCT_FLOOR


def test_slope_near_zero_matches_prior_ramp():
    # The logistic prior is tuned to ~6 win% per unit edge near the centre, so a
    # small edge behaves like the old linear ramp did.
    assert win_model.edge_to_win_pct(2) == 62      # 50 + 2*6, pre-logistic value


# -- fitting -----------------------------------------------------------------
def test_fit_recovers_a_separable_relationship():
    # Construct data where positive edge almost always wins and negative loses;
    # the fitted weight must be strongly positive.
    samples = []
    for edge in range(-5, 6):
        won = 1 if edge > 0 else 0
        samples += [(float(edge), won)] * 20
    w, b = win_model.fit_logistic(samples, epochs=3000, lr=0.1)
    assert w > win_model.SIGMOID_K            # sharper than the cautious prior
    # Learned model should now predict a clear favourite at edge +3.
    assert win_model.win_probability(3.0, w, b) > 0.8


def test_fit_empty_returns_prior():
    assert win_model.fit_logistic([]) == (win_model.SIGMOID_K, win_model.SIGMOID_B)


# -- evaluation metrics ------------------------------------------------------
def test_brier_score_rewards_correctness():
    good = win_model.brier_score([0.9, 0.1], [1, 0])
    bad = win_model.brier_score([0.1, 0.9], [1, 0])
    assert good < bad
    assert abs(win_model.brier_score([0.5, 0.5], [1, 0]) - 0.25) < 1e-9


def test_calibration_bins_report_observed_vs_predicted():
    # Perfectly calibrated: in the 0.0 bucket nothing wins, in the 0.9 bucket all do.
    preds = [0.05, 0.05, 0.95, 0.95]
    outcomes = [0, 0, 1, 1]
    bins = win_model.calibration_bins(preds, outcomes, n_bins=10)
    for b in bins:
        assert abs(b["mean_pred"] - b["observed"]) < 0.1
    assert sum(b["count"] for b in bins) == 4
