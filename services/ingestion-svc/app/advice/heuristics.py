"""The five rule-based post-game heuristics (roadmap §4.2).

Each returns a ``Finding`` (severity 0–100) or ``None`` when the player was
fine on that axis. All thresholds come from ``benchmarks.tuning()`` so they are
runtime-tunable; all rules are deterministic — same input, same advice.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.advice import benchmarks
from app.advice.timeline import TimelineView, distance


@dataclass(frozen=True)
class PlayerContext:
    participant_id: int
    team_id: int
    team_position: str
    champion_name: str
    deaths: int
    kills: int
    assists: int
    wards_placed: int
    control_wards_bought: int
    # Enemy champion names — feeds the counter-item coverage heuristic (the
    # post-game half of the draft loadout coach's closed loop). Default empty so
    # existing callers/tests keep working.
    enemy_champions: tuple = ()


@dataclass
class Finding:
    type: str
    severity: int
    message_key: str
    evidence: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "type": self.type,
            "severity": self.severity,
            "message_key": self.message_key,
            "evidence": self.evidence,
        }


# -- 1. death context ---------------------------------------------------------

def death_context(view: TimelineView, ctx: PlayerContext, tun: dict) -> Finding | None:
    deaths = view.deaths()
    if len(deaths) < tun["min_deaths_for_finding"]:
        return None

    radius = tun["death_nearby_radius"]
    counts = {"outnumbered": 0, "no_vision": 0, "objective_trade": 0}
    team_wards = view.ward_events(team_only=True)
    monster_kills = view.elite_monster_kills()

    for death in deaths:
        classified = False
        # outnumbered: more enemies than allies around the death spot, or a
        # multi-man kill (killer + 2+ assists) — frame positions are 1/min so
        # the kill-participant count is the sharper signal.
        involved = (1 if death.killer_id else 0) + len(death.assisting_ids)
        positions = view.positions_at(death.timestamp_ms)
        me = death.position or positions.get(ctx.participant_id)
        if me is not None:
            allies = enemies = 0
            for pid, pos in positions.items():
                if pid == ctx.participant_id or distance(pos, me) > radius:
                    continue
                if pid in view.team_ids:
                    allies += 1
                else:
                    enemies += 1
            if enemies >= allies + 2 or involved >= 3:
                counts["outnumbered"] += 1
                classified = True
        elif involved >= 3:
            counts["outnumbered"] += 1
            classified = True

        # no vision: no team ward placed near the death spot recently
        if me is not None:
            recent_ward = any(
                death.timestamp_ms - tun["death_ward_window_ms"]
                <= w.get("timestamp", 0)
                <= death.timestamp_ms
                for w in team_wards
                # WARD_PLACED events carry no position; recency alone is the
                # MVP signal, distance kicks in when Riot adds positions.
            )
            if not recent_ward:
                counts["no_vision"] += 1
                classified = True

        # objective trade: died in the window around a neutral objective take
        for mk in monster_kills:
            if abs(mk.get("timestamp", 0) - death.timestamp_ms) <= tun["death_objective_window_ms"]:
                mk_pos = mk.get("position")
                if me is None or mk_pos is None or distance(
                    me, (float(mk_pos["x"]), float(mk_pos["y"]))
                ) <= tun["death_objective_radius"]:
                    counts["objective_trade"] += 1
                    classified = True
                    break

        _ = classified  # per-death bucket bookkeeping only

    total = len(deaths)
    bad = max(counts.values())
    if bad == 0:
        return None
    dominant = max(counts, key=counts.get)  # ties → dict order = rule priority
    severity = min(100, int(60 * bad / total) + 4 * total)
    return Finding(
        type="death_context",
        severity=severity,
        message_key=f"death_{dominant}",
        evidence={"total_deaths": total, "dominant_count": bad, **counts},
    )


# -- 2. CS benchmark ----------------------------------------------------------

def cs_benchmark(view: TimelineView, ctx: PlayerContext, tun: dict) -> Finding | None:
    table = tun.get("cs_benchmarks") or benchmarks.CS_BENCHMARKS
    bench = table.get(ctx.team_position)
    if bench is None:  # UTILITY (and unknown roles) are exempt
        return None
    game_min = view.game_length_ms() / 60000
    deficits = []
    evidence: dict = {}
    for minute, target in bench.items():
        if game_min < minute + 1:
            continue
        cs = view.cs_at_minute(minute)
        if cs is None:
            continue
        deficit_pct = (target - cs) / target * 100
        evidence[f"cs{minute}"] = cs
        evidence[f"bench{minute}"] = target
        deficits.append(deficit_pct)
    if not deficits:
        return None
    worst = max(deficits)
    if worst < tun["cs_deficit_pct_floor"]:
        return None
    evidence["deficit_pct"] = round(worst, 1)
    return Finding(
        type="cs_benchmark",
        severity=min(100, int(worst * 2.5)),
        message_key="cs_low",
        evidence=evidence,
    )


# -- 3. item timing -----------------------------------------------------------

def item_timing(view: TimelineView, ctx: PlayerContext, tun: dict) -> Finding | None:
    game_min = view.game_length_ms() / 60000
    core_buys = sorted(
        (
            e
            for e in view.item_purchases()
            if e.get("itemId") in benchmarks.CORE_ITEM_IDS
        ),
        key=lambda e: e.get("timestamp", 0),
    )
    severity = 0.0
    evidence: dict = {}

    if game_min >= tun["first_core_minute"] + 1:
        first_min = core_buys[0]["timestamp"] / 60000 if core_buys else None
        evidence["bench_first"] = tun["first_core_minute"]
        if first_min is None:
            severity += 60
            evidence["first_core_min"] = None
        else:
            evidence["first_core_min"] = round(first_min, 1)
            evidence["first_item"] = benchmarks.CORE_ITEM_NAMES.get(core_buys[0]["itemId"], "?")
            delay = first_min - tun["first_core_minute"]
            if delay > 0:
                severity += delay * 8

    if game_min >= tun["second_core_minute"] + 1:
        second_min = core_buys[1]["timestamp"] / 60000 if len(core_buys) > 1 else None
        evidence["bench_second"] = tun["second_core_minute"]
        if second_min is None:
            severity += 30
            evidence["second_core_min"] = None
        else:
            evidence["second_core_min"] = round(second_min, 1)
            delay = second_min - tun["second_core_minute"]
            if delay > 0:
                severity += delay * 4

    # dead gold: consecutive frames sitting on a big unspent pile (after the
    # laning phase settles, minute 8+)
    run = best_run = 0
    for ts, gold in view.gold_series():
        if ts < 8 * 60000:
            continue
        if gold >= tun["dead_gold_threshold"]:
            run += 1
            best_run = max(best_run, run)
        else:
            run = 0
    if best_run >= tun["dead_gold_min_frames"]:
        severity += best_run * 5
        evidence["dead_gold_minutes"] = best_run

    if severity < 20:
        return None
    return Finding(
        type="item_timing",
        severity=min(100, int(severity)),
        message_key="item_slow",
        evidence=evidence,
    )


# -- 4. vision ------------------------------------------------------------------

def vision(view: TimelineView, ctx: PlayerContext, tun: dict) -> Finding | None:
    table = tun.get("vision_benchmarks") or benchmarks.VISION_BENCHMARKS
    bench = table.get(
        ctx.team_position,
        table.get("MIDDLE", benchmarks.VISION_BENCHMARKS["MIDDLE"]),
    )
    game_min = view.game_length_ms() / 60000
    if game_min < 12:
        return None
    wards_per_min = ctx.wards_placed / game_min
    deficit_pct = (bench["wards_per_min"] - wards_per_min) / bench["wards_per_min"] * 100
    cw_short = max(0, bench["control_wards"] - ctx.control_wards_bought)
    if deficit_pct < tun["vision_deficit_pct_floor"] and cw_short == 0:
        return None
    severity = max(0.0, deficit_pct * 0.8) + cw_short * 15
    return Finding(
        type="vision",
        severity=min(100, int(severity)),
        message_key="vision_low",
        evidence={
            "wards_per_min": round(wards_per_min, 2),
            "bench_wards_per_min": bench["wards_per_min"],
            "control_wards": ctx.control_wards_bought,
            "bench_control_wards": bench["control_wards"],
        },
    )


# -- 5. objective presence -------------------------------------------------------

def objective_presence(view: TimelineView, ctx: PlayerContext, tun: dict) -> Finding | None:
    team_kills = [
        mk
        for mk in view.elite_monster_kills()
        if mk.get("killerTeamId") == ctx.team_id
        or mk.get("killerId") in view.team_ids
    ]
    if len(team_kills) < tun["min_team_objectives"]:
        return None
    attended = 0
    for mk in team_kills:
        if mk.get("killerId") == ctx.participant_id or ctx.participant_id in (
            mk.get("assistingParticipantIds") or []
        ):
            attended += 1
            continue
        pos = mk.get("position")
        me = view.positions_at(mk.get("timestamp", 0)).get(ctx.participant_id)
        if pos and me and distance(me, (float(pos["x"]), float(pos["y"]))) <= tun["objective_radius"]:
            attended += 1
    ratio = attended / len(team_kills)
    if ratio >= tun["objective_participation_floor"]:
        return None
    severity = min(100, int((tun["objective_participation_floor"] - ratio) * 180) + 10)
    return Finding(
        type="objective_presence",
        severity=severity,
        message_key="objective_absent",
        evidence={
            "team_objectives": len(team_kills),
            "attended": attended,
            "ratio_pct": round(ratio * 100),
        },
    )


def _all_heuristics():
    # Imported lazily so counters.py can import Finding/PlayerContext from here
    # without a circular import at module load.
    from app.advice.counters import counter_item_coverage
    return (death_context, cs_benchmark, item_timing, vision,
            objective_presence, counter_item_coverage)


def run_all(view: TimelineView, ctx: PlayerContext, tun: dict | None = None) -> list[Finding]:
    tun = tun or benchmarks.tuning()
    findings = []
    for heuristic in _all_heuristics():
        finding = heuristic(view, ctx, tun)
        if finding is not None:
            findings.append(finding)
    return findings
