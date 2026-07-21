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

# ``data/benchmarks`` states vision as a per-game total, while this module scores
# it per minute. Converting needs a game-length assumption; 30 minutes is the
# rough Summoner's Rift average and keeps the two tables comparable.
_ASSUMED_GAME_MINUTES = 30.0

DEFAULT_WINDOW = 20
MIN_GAMES = 3  # below this the scores are too noisy to coach from

# Dimension weights for the overall score.
_WEIGHTS = {"farm": 0.25, "vision": 0.20, "combat": 0.30, "survival": 0.25}

_DIM_LABELS = {
    "farm": ("Farm", "CS/min"),
    "vision": ("Vision", "vision/min"),
    "combat": ("Combat", "KDA"),
    "survival": ("Survival", "deaths/game"),
}

# A goal is the next reachable step, not the ideal. Asking a 3.0 CS/min player
# for 9.6 is demotivating and unactionable in a single game; +10 score points is
# a step they can actually take next match.
_GOAL_STEP = 10
_GOAL_MAX_SCORE = 95


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


def rank_baselines(tier: str | None) -> dict[str, dict]:
    """Per-role baselines calibrated to the player's own rank band.

    Without this every player is graded against one high-elo constant, so a Gold
    laner reads red on essentially every game. ``data/benchmarks`` already holds
    the band × role table the Players tab uses; this adapts it to the metric
    shape this module scores against. Damage has no band benchmark yet, so it
    keeps the role default.
    """
    from sylqon.data import benchmarks

    out: dict[str, dict] = {}
    for role in benchmarks.ROLES:
        b = benchmarks.benchmark(role, tier) or {}
        default = _ROLE_BASELINES.get(role, _DEFAULT_BASELINE)
        vision = b.get("vision_score")
        out[role] = {
            "cs_min": b.get("cs_per_min") or default["cs_min"],
            "vis_min": (vision / _ASSUMED_GAME_MINUTES) if vision else default["vis_min"],
            "deaths": b.get("deaths") or default["deaths"],
            "dmg_min": default["dmg_min"],
        }
    return out


def build_scorecard(matches: list[dict], *, window: int = DEFAULT_WINDOW,
                    baselines: dict[str, dict] | None = None) -> dict:
    """Aggregate up to ``window`` newest games into the coach scorecard.

    ``baselines`` overrides the built-in role table (see :func:`rank_baselines`)
    so the same game scores differently for a Silver and a Diamond player.
    """
    table = baselines or _ROLE_BASELINES
    games = (matches or [])[:window]
    n = len(games)
    if n == 0:
        return {"games_analyzed": 0, "insufficient": True, "win_rate": None,
                "recent_results": [], "overall": 0,
                "overall_trend": {"dir": "flat", "delta": 0},
                "primary_role": "",
                "dimensions": [d | {"value": "—", "raw": 0.0, "score": 0,
                                    "trend": {"dir": "flat", "delta": 0}}
                               for d in _empty_dims()]}

    # Per-game scores (newest first) + raw metric accumulators for display.
    series = {k: [] for k in _WEIGHTS}
    raw = {"cs": [], "vis": [], "kda": [], "deaths": []}
    wins = 0
    results = []
    role_counts: dict[str, int] = {}

    for g in games:
        role = g.get("role") or ""
        base = table.get(role, _DEFAULT_BASELINE)
        if role:
            role_counts[role] = role_counts.get(role, 0) + 1
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
        "farm": (f"{avg(raw['cs']):.1f}", "CS/min"),
        "vision": (f"{avg(raw['vis']):.2f}", "vision/min"),
        "combat": (f"{avg(raw['kda']):.2f}", "KDA"),
        "survival": (f"{avg(raw['deaths']):.1f}", "deaths/game"),
    }

    # Numeric twin of raw_display — the display strings are formatted for the UI,
    # but the goal maths needs the unrounded value.
    raw_numeric = {"farm": avg(raw["cs"]), "vision": avg(raw["vis"]),
                   "combat": avg(raw["kda"]), "survival": avg(raw["deaths"])}

    dimensions = []
    for key in ("farm", "vision", "combat", "survival"):
        label, _ = _DIM_LABELS[key]
        value, unit = raw_display[key]
        dimensions.append({
            "key": key, "label": label, "unit": unit, "value": value,
            "raw": round(raw_numeric[key], 3),
            "score": round(avg(series[key])),
            "trend": _trend(series[key]),
        })

    overall = round(sum(d["score"] * _WEIGHTS[d["key"]] for d in dimensions))
    overall_series = [
        sum(series[k][i] * _WEIGHTS[k] for k in _WEIGHTS if i < len(series[k]))
        for i in range(n)
    ]
    primary_role = max(role_counts, key=role_counts.get) if role_counts else ""
    return {
        "games_analyzed": n,
        "insufficient": n < MIN_GAMES,
        "win_rate": round(wins / n, 3),
        "recent_results": results[:10],
        "overall": overall,
        "overall_trend": _trend(overall_series),
        "primary_role": primary_role,
        "dimensions": dimensions,
    }


def build_progress(current: dict, previous: dict) -> dict:
    """Score movement between the current window and the one before it.

    This is what turns the coach from a snapshot into a progress read: the same
    deterministic scorecard computed over ``matches[window:window*2]`` gives an
    honest "where you were" baseline without storing any history.

    ``available`` is false when the older window is too thin to compare against —
    the UI then shows the plain score rather than a misleading delta of zero.
    """
    prev_games = (previous or {}).get("games_analyzed", 0)
    available = prev_games >= MIN_GAMES and not (current or {}).get("insufficient", True)
    prev_dims = {d["key"]: d for d in (previous or {}).get("dimensions", [])}

    dims = {}
    for d in (current or {}).get("dimensions", []):
        prev = prev_dims.get(d["key"])
        dims[d["key"]] = {
            "previous_score": prev["score"] if prev else None,
            "delta": (d["score"] - prev["score"]) if (available and prev) else None,
        }
    return {
        "available": available,
        "compared_games": prev_games,
        "previous_overall": previous.get("overall") if available else None,
        "overall_delta": (current["overall"] - previous["overall"]) if available else None,
        "dimensions": dims,
    }


def _target_value(key: str, baseline: float, target_score: float) -> float:
    """Invert ``_ratio_score``: the metric value that would earn ``target_score``."""
    if key == "survival":  # lower is better
        return 50.0 * baseline / max(target_score, 1.0)
    return target_score * baseline / 50.0


def derive_goal(scorecard: dict, baselines: dict[str, dict] | None = None) -> dict | None:
    """The single next-match target: lift the weakest dimension to a real number.

    Deterministic and LLM-free, so the CTA still has something concrete to say
    when Ollama is offline. Returns ``None`` when there is not enough data to
    name a weak spot honestly.
    """
    if not scorecard or scorecard.get("insufficient"):
        return None
    dims = [d for d in scorecard.get("dimensions", []) if d.get("value") != "—"]
    if not dims:
        return None

    weakest = min(dims, key=lambda d: d["score"])
    role = scorecard.get("primary_role", "")
    table = baselines or _ROLE_BASELINES
    base = table.get(role, _DEFAULT_BASELINE)
    metric_key = {"farm": "cs_min", "vision": "vis_min",
                  "survival": "deaths", "combat": None}[weakest["key"]]

    # Combat has no single baseline metric (it blends KDA and damage), so it
    # gets a score goal rather than a metric goal.
    target_score = min(weakest["score"] + _GOAL_STEP, _GOAL_MAX_SCORE)
    if metric_key is None:
        return {"key": weakest["key"], "label": weakest["label"], "unit": weakest["unit"],
                "current": weakest["raw"], "target": None,
                "current_score": weakest["score"], "target_score": target_score}

    target = _target_value(weakest["key"], base[metric_key], target_score)
    precision = 2 if weakest["key"] == "vision" else 1
    return {
        "key": weakest["key"], "label": weakest["label"], "unit": weakest["unit"],
        "current": weakest["raw"], "target": round(target, precision),
        "current_score": weakest["score"], "target_score": target_score,
    }


def _empty_dims() -> list[dict]:
    out = []
    for key in ("farm", "vision", "combat", "survival"):
        label, unit = _DIM_LABELS[key]
        out.append({"key": key, "label": label, "unit": unit})
    return out
