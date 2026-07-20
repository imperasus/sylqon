"""Calibratable win-probability model + evaluation harness (pure, deterministic).

The old draft win% was ``clamp(50 + edge*6, 35, 65)`` — a linear ramp with an
arbitrary hard band, no probability semantics and no way to check it against
reality. This replaces the *form* with a logistic (the correct shape for a
bounded probability) whose single slope coefficient is **calibratable**, and
adds the harness that makes calibration possible:

  * :func:`edge_to_win_pct` — the model used in production (logistic, softly
    bounded so a draft heuristic never screams a blowout);
  * :func:`fit_logistic` — plain-Python gradient-descent logistic regression that
    fits ``(weight, bias)`` from labelled ``(edge, won)`` samples, so once the
    hosted Match-V5 pipeline supplies real drafted-game outcomes the coefficient
    stops being a guess;
  * :func:`brier_score` / :func:`calibration_bins` — the validation metrics
    (lower Brier = sharper+calibrated; the reliability curve shows over/under
    confidence per bucket).

No numpy/sklearn — a few hundred samples fit fine in pure Python, and it keeps
the offline test suite dependency-free and deterministic.
"""
from __future__ import annotations

import math

# Production coefficient. Chosen so the logistic's slope at edge 0 matches the
# old linear ramp (~6 win% per unit edge): d/dx[100·σ(k·x)]|₀ = 25k = 6 → k≈0.24.
# This is the *prior*; :func:`fit_logistic` replaces it from real outcomes.
SIGMOID_K = 0.24
SIGMOID_B = 0.0
# Soft bounds: a draft-time read is uncertain, so we never claim beyond this.
WIN_PCT_FLOOR, WIN_PCT_CEIL = 20.0, 80.0


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def win_probability(edge: float, weight: float = SIGMOID_K,
                    bias: float = SIGMOID_B) -> float:
    """Logistic win probability in [0, 1] for a signed draft ``edge``."""
    return _sigmoid(weight * edge + bias)


def edge_to_win_pct(edge: float, weight: float = SIGMOID_K,
                    bias: float = SIGMOID_B) -> int:
    """Production mapping: signed edge → integer win% (softly bounded)."""
    pct = win_probability(edge, weight, bias) * 100.0
    return int(round(max(WIN_PCT_FLOOR, min(WIN_PCT_CEIL, pct))))


def fit_logistic(samples: list[tuple[float, int]], *, epochs: int = 2000,
                 lr: float = 0.05) -> tuple[float, float]:
    """Fit ``(weight, bias)`` of ``σ(weight·edge + bias)`` to labelled samples by
    gradient descent on log-loss. ``samples`` is ``[(edge, won)]`` with
    ``won ∈ {0, 1}``. Deterministic (fixed init, full-batch). Returns the prior
    unchanged when there is nothing to fit."""
    if not samples:
        return SIGMOID_K, SIGMOID_B
    w, b = SIGMOID_K, SIGMOID_B
    n = len(samples)
    for _ in range(epochs):
        gw = gb = 0.0
        for edge, won in samples:
            pred = _sigmoid(w * edge + b)
            err = pred - won
            gw += err * edge
            gb += err
        w -= lr * gw / n
        b -= lr * gb / n
    return w, b


def brier_score(preds: list[float], outcomes: list[int]) -> float:
    """Mean squared error of probabilistic predictions vs {0,1} outcomes. Lower
    is better; 0.25 is the score of always guessing 0.5."""
    if not preds:
        return 0.0
    return sum((p - o) ** 2 for p, o in zip(preds, outcomes)) / len(preds)


def calibration_bins(preds: list[float], outcomes: list[int],
                     n_bins: int = 10) -> list[dict]:
    """Reliability curve: bucket predictions into ``n_bins`` and report, per
    non-empty bucket, the mean predicted probability vs the observed win rate.
    A well-calibrated model has ``mean_pred ≈ observed`` in every bucket."""
    buckets: list[list[tuple[float, int]]] = [[] for _ in range(n_bins)]
    for p, o in zip(preds, outcomes):
        idx = min(n_bins - 1, max(0, int(p * n_bins)))
        buckets[idx].append((p, o))
    out = []
    for i, bucket in enumerate(buckets):
        if not bucket:
            continue
        out.append({
            "bin": i,
            "count": len(bucket),
            "mean_pred": round(sum(p for p, _ in bucket) / len(bucket), 4),
            "observed": round(sum(o for _, o in bucket) / len(bucket), 4),
        })
    return out
