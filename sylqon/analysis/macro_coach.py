"""Account-level performance scorecard for the AI Macro Coach (feature A).

Deterministic, network- and LLM-free: aggregates the last N stored Summoner's
Rift games into four role-aware dimension scores (Farm / Vision / Combat /
Survival), a per-dimension trend, an overall score and the recent W/L streak.
This always works (no Ollama needed); the LLM only turns this scorecard into the
"top 3 things to improve" prose (see ``ai/macro_coach_prompt.py``).

Each game is scored against the baseline for *its own* role, then averaged, so a
mixed-role history (e.g. an ADC main who flexes support) is read correctly — a
support's low CS/min is not penalised like an ADC's would be.

Input is a list of serialized match dicts (newest first) as produced by
``db.matches.serialize_match``: ``{result, role, kda{kills,deaths,assists},
stats{duration, cs_per_min, vision_score, total_damage, ...}}``.
"""
from __future__ import annotations

# "Good" current-meta benchmarks per role. A metric exactly on baseline scores
# 50; double the baseline (or half, for deaths) saturates at 100. Tunable.
_ROLE_BASELINES = {
    "top":     {"cs_min": 7.0, "vis_min": 0.55, "deaths": 4.5, "dmg_min": 600},
    "jungle":  {"cs_min": 5.5, "vis_min": 0.85, "deaths": 4.5, "dmg_min": 500},
    "middle":  {"cs_min": 7.5, "vis_min": 0.60, "deaths": 4.0, "dmg_min": 750},
    "bottom":  {"cs_min": 8.0, "vis_min": 0.50, "deaths": 4.0, "dmg_min": 800},
    "utility": {"cs_min": 1.5, "vis_min": 1.30, "deaths": 5.0, "dmg_min": 300},
}
_DEFAULT_BASELINE = {"cs_min": 6.5, "vis_min": 0.70, "deaths": 4.5, "dmg_min": 600}
_KDA_BASELINE = 3.0

DEFAULT_WINDOW = 20
MIN_GAMES = 3  # below this the scores are too noisy to coach from

# Dimension weights for the overall score.
_WEIGHTS = {"farm": 0.25, "vision": 0.20, "combat": 0.30, "survival": 0.25}

_DIM_LABELS = {
    "farm": ("Farm", "CS/perc"),
    "vision": ("Vízió", "vízió/perc"),
    "combat": ("Harc", "KDA"),
    "survival": ("Túlélés", "halál/meccs"),
}


def _ratio_score(value: float, baseline: float, *, higher_better: bool = True) -> float:
    """Map a metric to 0-100 where value==baseline -> 50. Higher-better metrics
    double to reach 100; for lower-better, halving the baseline reaches 100."""
    if baseline <= 0:
        return 50.0
    if higher_better:
        return max(0.0, min(100.0, 50.0 * value / baseline))
    return max(0.0, min(100.0, 50.0 * baseline / max(value, 0.1)))


def _trend(scores: list[float]) -> dict:
    """Compare the recent half of a per-game score series (newest first) against
    the older half. ``delta`` is in score points."""
    if len(scores) < 4:
        return {"dir": "flat", "delta": 0}
    half = len(scores) // 2
    recent = sum(scores[:half]) / half
    older = sum(scores[half:]) / (len(scores) - half)
    delta = round(recent - older)
    direction = "up" if delta >= 5 else "down" if delta <= -5 else "flat"
    return {"dir": direction, "delta": delta}


def _per_minute(total: float, duration_s: float) -> float | None:
    return (total / (duration_s / 60.0)) if duration_s and duration_s > 0 else None


def build_scorecard(matches: list[dict], *, window: int = DEFAULT_WINDOW) -> dict:
    """Aggregate up to ``window`` newest games into the coach scorecard."""
    games = (matches or [])[:window]
    n = len(games)
    if n == 0:
        return {"games_analyzed": 0, "insufficient": True, "win_rate": None,
                "recent_results": [], "overall": 0,
                "overall_trend": {"dir": "flat", "delta": 0},
                "dimensions": [d | {"value": "—", "score": 0,
                                    "trend": {"dir": "flat", "delta": 0}}
                               for d in _empty_dims()]}

    # Per-game scores (newest first) + raw metric accumulators for display.
    series = {k: [] for k in _WEIGHTS}
    raw = {"cs": [], "vis": [], "kda": [], "deaths": []}
    wins = 0
    results = []

    for g in games:
        role = g.get("role") or ""
        base = _ROLE_BASELINES.get(role, _DEFAULT_BASELINE)
        stats = g.get("stats") or {}
        kda = g.get("kda") or {}
        dur = stats.get("duration", 0) or 0

        win = g.get("result") == "Win"
        wins += 1 if win else 0
        results.append("W" if win else "L")

        cs_min = stats.get("cs_per_min", 0) or 0.0
        series["farm"].append(_ratio_score(cs_min, base["cs_min"]))
        raw["cs"].append(cs_min)

        vis_min = _per_minute(stats.get("vision_score", 0) or 0, dur)
        if vis_min is not None:
            series["vision"].append(_ratio_score(vis_min, base["vis_min"]))
            raw["vis"].append(vis_min)

        deaths = kda.get("deaths", 0) or 0
        series["survival"].append(_ratio_score(deaths, base["deaths"], higher_better=False))
        raw["deaths"].append(deaths)

        kda_ratio = (kda.get("kills", 0) + kda.get("assists", 0)) / max(deaths, 1)
        dmg_min = _per_minute(stats.get("total_damage", 0) or 0, dur)
        combat = 0.6 * _ratio_score(kda_ratio, _KDA_BASELINE)
        combat += 0.4 * (_ratio_score(dmg_min, base["dmg_min"]) if dmg_min is not None else 50.0)
        series["combat"].append(combat)
        raw["kda"].append(kda_ratio)

    def avg(xs: list[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    raw_display = {
        "farm": (f"{avg(raw['cs']):.1f}", "CS/perc"),
        "vision": (f"{avg(raw['vis']):.2f}", "vízió/perc"),
        "combat": (f"{avg(raw['kda']):.2f}", "KDA"),
        "survival": (f"{avg(raw['deaths']):.1f}", "halál/meccs"),
    }

    dimensions = []
    for key in ("farm", "vision", "combat", "survival"):
        label, _ = _DIM_LABELS[key]
        value, unit = raw_display[key]
        dimensions.append({
            "key": key, "label": label, "unit": unit, "value": value,
            "score": round(avg(series[key])),
            "trend": _trend(series[key]),
        })

    overall = round(sum(d["score"] * _WEIGHTS[d["key"]] for d in dimensions))
    overall_series = [
        sum(series[k][i] * _WEIGHTS[k] for k in _WEIGHTS if i < len(series[k]))
        for i in range(n)
    ]
    return {
        "games_analyzed": n,
        "insufficient": n < MIN_GAMES,
        "win_rate": round(wins / n, 3),
        "recent_results": results[:10],
        "overall": overall,
        "overall_trend": _trend(overall_series),
        "dimensions": dimensions,
    }


def _empty_dims() -> list[dict]:
    out = []
    for key in ("farm", "vision", "combat", "survival"):
        label, unit = _DIM_LABELS[key]
        out.append({"key": key, "label": label, "unit": unit})
    return out
