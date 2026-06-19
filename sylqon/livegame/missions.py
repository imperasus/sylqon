"""Role-aware mission catalog + pure evaluators (overlay coach, Phase 2).

A `Mission` is a static template; a `MissionRuntime` tracks one in-flight attempt
(baseline counters captured at assignment + status/progress). Every evaluator is
a **pure function of the live snapshot vs the baseline** — it only uses
information the player already sees (CS, deaths, wards, objective events, timers),
never hidden state. Standard tuning lives here; Phase 5 lets `config` override it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sylqon import config
from sylqon.livegame.state import LiveGameState

# -- mission types -----------------------------------------------------------
NO_DEATH = "no_death_for_duration"
FARM_CS_DELTA = "farm_cs_delta"
CS_PER_MIN = "cs_per_min_threshold"
OBJECTIVE = "objective_control"
WARDING = "warding"
ROAM_ASSIST = "roam_assist"
GANK_ASSIST = "gank_assist"


# -- Standard tuning (env/config overridable in Phase 5 via config.MISSION_TUNING) --
_DEFAULT_TUNING = {
    "no_death_short": 120,
    "no_death_farm": 150,
    "cs_delta": 30, "cs_window": 180,
    "adc_cs_delta": 30,
    "cspm_target": 7.5, "cspm_window": 180,
    "objective_window": 240,
    "jg_ward_count": 3, "sup_ward_count": 4, "ward_window": 180,
    "takedown_window": 180,
}


def _t(key: str) -> float:
    override = getattr(config, "MISSION_TUNING", {}) or {}
    return override.get(key, _DEFAULT_TUNING[key])


@dataclass(frozen=True)
class Mission:
    id: str
    role: str                  # top/jungle/middle/bottom/utility
    type: str
    params: dict
    reward_points: int
    text: str                  # ≤ 1 short sentence


@dataclass
class MissionRuntime:
    mission: Mission
    started_at: float          # live game_time at assignment
    baseline: dict             # counters captured at assignment
    status: str = "active"     # active | completed | failed
    progress: float = 0.0      # 0..1
    detail: str = ""
    deadline: float = 0.0      # game_time deadline (0 = open-ended)


# -- baseline + helpers ------------------------------------------------------
def _counters(live: LiveGameState) -> dict:
    obj = live.objectives or {}

    def ally(k: str) -> int:
        return int((obj.get(k) or {}).get("ally", 0))

    return {
        "deaths": live.deaths, "cs": live.cs, "ward_score": live.ward_score,
        "kills": live.kills, "assists": live.assists,
        "takedowns": live.kills + live.assists,
        "dragons": ally("dragons"), "heralds": ally("heralds"),
        "barons": ally("barons"), "towers": ally("towers"),
    }


def make_runtime(mission: Mission, live: LiveGameState) -> MissionRuntime:
    dur = mission.params.get("duration", 0)
    return MissionRuntime(
        mission=mission, started_at=live.game_time, baseline=_counters(live),
        deadline=(live.game_time + dur) if dur else 0.0,
    )


def _left(m: Mission, rt: MissionRuntime, live: LiveGameState) -> int:
    return max(0, int(rt.started_at + m.params.get("duration", 0) - live.game_time))


# -- evaluators: (status, progress, detail) ----------------------------------
def _eval_no_death(m, rt, live):
    if live.deaths - rt.baseline["deaths"] > 0:
        return "failed", 0.0, "You died — try again"
    dur = m.params["duration"]
    elapsed = live.game_time - rt.started_at
    if elapsed >= dur:
        return "completed", 1.0, "Survived!"
    return "active", min(1.0, elapsed / dur), f"{_left(m, rt, live)}s left"


def _eval_farm(m, rt, live):
    if m.params.get("no_death") and live.deaths - rt.baseline["deaths"] > 0:
        return "failed", 0.0, "Died before the farm goal"
    gained = live.cs - rt.baseline["cs"]
    target = m.params["cs_delta"]
    if gained >= target:
        return "completed", 1.0, f"+{gained} CS"
    if m.params.get("duration") and live.game_time >= rt.deadline:
        return "failed", min(1.0, gained / target), f"Only +{gained}/{target} CS"
    return "active", min(1.0, gained / max(1, target)), f"+{gained}/{target} CS"


def _eval_cspm(m, rt, live):
    if m.params.get("no_death") and live.deaths - rt.baseline["deaths"] > 0:
        return "failed", 0.0, "Died"
    dur = m.params["duration"]
    elapsed = live.game_time - rt.started_at
    gained = live.cs - rt.baseline["cs"]
    cspm = gained / (elapsed / 60.0) if elapsed > 0 else 0.0
    target = m.params["cs_per_min"]
    if elapsed >= dur:
        if cspm >= target:
            return "completed", 1.0, f"{cspm:.1f} CS/min"
        return "failed", min(1.0, cspm / target), f"{cspm:.1f}/{target} CS/min"
    return "active", min(1.0, elapsed / dur), f"{cspm:.1f} CS/min · {_left(m, rt, live)}s"


def _eval_objective(m, rt, live):
    kinds = m.params.get("objectives", ["dragons", "heralds"])
    cur = _counters(live)
    gained = sum(cur[k] - rt.baseline.get(k, 0) for k in kinds)
    target = m.params.get("count", 1)
    if gained >= target:
        return "completed", 1.0, f"{gained} secured"
    if m.params.get("duration") and live.game_time >= rt.deadline:
        return "failed", min(1.0, gained / target), f"{gained}/{target} secured"
    return "active", min(1.0, gained / max(1, target)), f"{gained}/{target} · {_left(m, rt, live)}s"


def _eval_warding(m, rt, live):
    gained = live.ward_score - rt.baseline["ward_score"]
    target = m.params["ward_count"]
    if gained >= target:
        return "completed", 1.0, f"+{gained:.0f} vision"
    if m.params.get("duration") and live.game_time >= rt.deadline:
        return "failed", min(1.0, gained / target), f"+{gained:.0f}/{target} vision"
    return "active", min(1.0, gained / max(1, target)), f"+{gained:.0f}/{target} · {_left(m, rt, live)}s"


def _eval_takedown(m, rt, live):
    gained = (live.kills + live.assists) - rt.baseline["takedowns"]
    target = m.params.get("count", 1)
    if gained >= target:
        return "completed", 1.0, f"{gained} takedown(s)"
    if m.params.get("duration") and live.game_time >= rt.deadline:
        return "failed", min(1.0, gained / target), f"{gained}/{target} takedowns"
    return "active", min(1.0, gained / max(1, target)), f"{gained}/{target} · {_left(m, rt, live)}s"


EVALUATORS = {
    NO_DEATH: _eval_no_death,
    FARM_CS_DELTA: _eval_farm,
    CS_PER_MIN: _eval_cspm,
    OBJECTIVE: _eval_objective,
    WARDING: _eval_warding,
    ROAM_ASSIST: _eval_takedown,
    GANK_ASSIST: _eval_takedown,
}


# -- AI-generated mission validation -----------------------------------------
# The closed vocabulary the AI may emit: per type, the params it must/​may carry
# and the numeric clamp ranges. This doubles as prompt documentation
# (``MISSION_TYPE_SCHEMA``) and as the validator's source of truth — nothing is
# stored that the live evaluators above cannot score.
OBJECTIVE_KINDS = ("dragons", "heralds", "barons", "towers")
REWARD_RANGE = (10, 50)
_DURATION = (60, 360)

MISSION_TYPE_SCHEMA: dict[str, dict] = {
    NO_DEATH: {"int": {"duration": _DURATION}},
    FARM_CS_DELTA: {"int": {"cs_delta": (10, 90)}, "opt_int": {"duration": _DURATION},
                    "opt_bool": ("no_death",)},
    CS_PER_MIN: {"float": {"cs_per_min": (4.0, 10.0)}, "int": {"duration": _DURATION}},
    OBJECTIVE: {"int": {"count": (1, 3)}, "opt_int": {"duration": _DURATION},
                "enum_list": {"objectives": OBJECTIVE_KINDS}},
    WARDING: {"int": {"ward_count": (2, 8)}, "opt_int": {"duration": _DURATION}},
    ROAM_ASSIST: {"int": {"count": (1, 3)}, "opt_int": {"duration": _DURATION}},
    GANK_ASSIST: {"int": {"count": (1, 3)}, "opt_int": {"duration": _DURATION}},
}


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def normalize_mission(raw: dict) -> dict | None:
    """Validate one raw AI mission against ``MISSION_TYPE_SCHEMA`` and return a
    storable ``{type, params, reward_points, text}`` dict with every value
    clamped into range — or ``None`` if the type is unknown or a required param
    is missing/non-numeric. Mirrors the project rule that all AI output is
    checked against static tables before it is trusted."""
    if not isinstance(raw, dict):
        return None
    mtype = raw.get("type")
    schema = MISSION_TYPE_SCHEMA.get(mtype)
    if schema is None or mtype not in EVALUATORS:
        return None
    src = raw.get("params") or {}
    params: dict = {}

    try:
        for field_, (lo, hi) in schema.get("int", {}).items():
            params[field_] = int(_clamp(int(src[field_]), lo, hi))
        for field_, (lo, hi) in schema.get("float", {}).items():
            params[field_] = float(_clamp(float(src[field_]), lo, hi))
    except (KeyError, TypeError, ValueError):
        return None  # a required numeric param is missing or unparseable

    for field_, (lo, hi) in schema.get("opt_int", {}).items():
        if src.get(field_) is not None:
            try:
                params[field_] = int(_clamp(int(src[field_]), lo, hi))
            except (TypeError, ValueError):
                pass
    for field_ in schema.get("opt_bool", ()):  # type: ignore[assignment]
        if field_ in src:
            params[field_] = bool(src[field_])
    for field_, allowed in schema.get("enum_list", {}).items():
        picked = [k for k in (src.get(field_) or []) if k in allowed]
        params[field_] = picked or list(allowed[:2])  # sane default if AI sent junk

    try:
        reward = int(_clamp(int(raw.get("reward_points", 20)), *REWARD_RANGE))
    except (TypeError, ValueError):
        reward = 20
    text = str(raw.get("text") or "").strip()[:90] or _fallback_text(mtype, params)
    return {"type": mtype, "params": params, "reward_points": reward, "text": text}


def _fallback_text(mtype: str, params: dict) -> str:
    if mtype == NO_DEATH:
        return f"Don't die for {params.get('duration', 120)}s."
    if mtype == FARM_CS_DELTA:
        return f"Farm +{params.get('cs_delta', 30)} CS."
    if mtype == CS_PER_MIN:
        return f"Hold {params.get('cs_per_min', 7)}+ CS/min."
    if mtype == OBJECTIVE:
        return f"Secure {params.get('count', 1)} objective(s)."
    if mtype == WARDING:
        return f"Place {params.get('ward_count', 3)} wards."
    return f"Get {params.get('count', 1)} takedown(s)."


def mission_from_row(row, role: str) -> Mission:
    """Build a live ``Mission`` template from a stored ``ChampionMission`` row.
    The id is tagged ``cm:<row id>`` so the runtime can flip the exact row to
    completed when the engine resolves it."""
    return Mission(id=f"cm:{row.id}", role=role, type=row.mission_type,
                   params=dict(row.params or {}), reward_points=row.reward_points,
                   text=row.text)


def evaluate(rt: MissionRuntime, live: LiveGameState) -> tuple[str, float, str]:
    """Pure: classify a runtime against the live snapshot."""
    fn = EVALUATORS.get(rt.mission.type)
    if fn is None:
        return "active", 0.0, ""
    return fn(rt.mission, rt, live)


# -- role catalog (Standard) -------------------------------------------------
def _build_catalog() -> dict[str, list[Mission]]:
    return {
        "top": [
            Mission("top_no_death", "top", NO_DEATH, {"duration": _t("no_death_short")},
                    20, "Don't die for 2 minutes."),
            Mission("top_farm_safe", "top", FARM_CS_DELTA,
                    {"cs_delta": _t("cs_delta"), "duration": _t("no_death_farm"), "no_death": True},
                    30, "Farm +30 CS without dying."),
            Mission("top_splitpush", "top", NO_DEATH, {"duration": _t("no_death_short")},
                    25, "Split-push 2 minutes without dying."),
        ],
        "jungle": [
            Mission("jg_objective", "jungle", OBJECTIVE,
                    {"objectives": ["dragons", "heralds"], "count": 1, "duration": _t("objective_window")},
                    30, "Secure a dragon or herald in 4 min."),
            Mission("jg_ward", "jungle", WARDING,
                    {"ward_count": _t("jg_ward_count"), "duration": _t("ward_window")},
                    20, "Place or clear 3 wards in 3 min."),
            Mission("jg_gank", "jungle", GANK_ASSIST,
                    {"count": 1, "duration": _t("takedown_window")},
                    25, "Get a kill or assist ganking (3 min)."),
        ],
        "middle": [
            Mission("mid_cspm", "middle", CS_PER_MIN,
                    {"cs_per_min": _t("cspm_target"), "duration": _t("cspm_window")},
                    25, "Hold 7.5+ CS/min for 3 minutes."),
            Mission("mid_roam", "middle", ROAM_ASSIST,
                    {"count": 1, "duration": _t("takedown_window")},
                    25, "Roam and get a takedown (3 min)."),
            Mission("mid_farm_safe", "middle", FARM_CS_DELTA,
                    {"cs_delta": _t("cs_delta"), "duration": _t("no_death_farm"), "no_death": True},
                    30, "Farm +30 CS without dying."),
        ],
        "bottom": [
            Mission("adc_farm", "bottom", FARM_CS_DELTA,
                    {"cs_delta": _t("adc_cs_delta"), "duration": _t("cs_window")},
                    30, "Farm +30 CS in 3 minutes."),
            Mission("adc_no_death_cs", "bottom", FARM_CS_DELTA,
                    {"cs_delta": 20, "duration": _t("no_death_short"), "no_death": True},
                    30, "Survive 2 min while farming."),
            Mission("adc_survive", "bottom", NO_DEATH, {"duration": _t("no_death_short")},
                    25, "Survive the next 2 minutes — no deaths."),
        ],
        "utility": [
            Mission("sup_ward", "utility", WARDING,
                    {"ward_count": _t("sup_ward_count"), "duration": _t("ward_window")},
                    25, "Place or clear 4 wards in 3 min."),
            Mission("sup_no_death", "utility", NO_DEATH, {"duration": _t("no_death_short")},
                    20, "Don't die for 2 minutes."),
            Mission("sup_engage", "utility", ROAM_ASSIST,
                    {"count": 1, "duration": _t("takedown_window")},
                    25, "Land an engage or peel takedown (3 min)."),
        ],
    }


ROLE_CATALOG: dict[str, list[Mission]] = _build_catalog()
