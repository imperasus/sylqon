"""Own-data benchmark aggregation — the first step of replacing the seed
tables (and eventually the local app's op.gg dependency) with medians computed
from our own Match-V5 ingestion.

Every stored Summoner's Rift match contributes all 10 participants, so the
sample pool grows 10× faster than the tracked-player count. Until a role
clears ``BENCHMARK_MIN_SAMPLES``, the advice heuristics keep using the curated
seed values.
"""
from __future__ import annotations

import logging
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.models import ComputedBenchmark, Match, Timeline

log = logging.getLogger(__name__)

# Summoner's Rift queues: ranked solo, ranked flex, normal draft, normal blind.
SR_QUEUES = {420, 440, 400, 430}

ROLES = ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")


def _cs_at(frames: list[dict], pid: int, minute: int) -> int | None:
    if len(frames) <= minute:
        return None
    pf = frames[minute].get("participantFrames", {}).get(str(pid))
    if pf is None:
        return None
    return int(pf.get("minionsKilled", 0)) + int(pf.get("jungleMinionsKilled", 0))


def compute_role_benchmarks(session: Session) -> dict[str, dict]:
    """Aggregate per-role medians from every stored SR match + timeline."""
    samples: dict[str, dict[str, list[float]]] = {
        role: {"cs10": [], "cs15": [], "wards_per_min": [], "control_wards": []}
        for role in ROLES
    }

    rows = session.execute(
        select(Match, Timeline).join(Timeline, Timeline.match_id == Match.match_id)
    )
    for match, timeline in rows:
        if match.queue_id not in SR_QUEUES:
            continue
        duration_min = (match.game_duration or 0) / 60
        if duration_min < 16:  # remakes/stomps skew medians
            continue
        frames = timeline.payload.get("frames", [])
        for p in match.raw.get("participants", []):
            role = p.get("teamPosition")
            pid = p.get("participantId")
            if role not in samples or not pid:
                continue
            bucket = samples[role]
            cs10 = _cs_at(frames, pid, 10)
            cs15 = _cs_at(frames, pid, 15)
            if cs10 is not None:
                bucket["cs10"].append(cs10)
            if cs15 is not None:
                bucket["cs15"].append(cs15)
            bucket["wards_per_min"].append(p.get("wardsPlaced", 0) / duration_min)
            bucket["control_wards"].append(p.get("visionWardsBoughtInGame", 0))

    out: dict[str, dict] = {}
    for role, bucket in samples.items():
        n = len(bucket["wards_per_min"])
        if n == 0:
            continue
        out[role] = {
            "cs10": round(median(bucket["cs10"])) if bucket["cs10"] else None,
            "cs15": round(median(bucket["cs15"])) if bucket["cs15"] else None,
            "wards_per_min": round(median(bucket["wards_per_min"]), 2),
            "control_wards": round(median(bucket["control_wards"])),
            "samples": n,
        }
    return out


def refresh_benchmarks(session: Session) -> dict[str, dict]:
    """Recompute and upsert the computed_benchmarks table."""
    computed = compute_role_benchmarks(session)
    for role, data in computed.items():
        row = session.get(ComputedBenchmark, role) or ComputedBenchmark(role=role)
        row.data = {k: v for k, v in data.items() if k != "samples"}
        row.samples = data["samples"]
        session.add(row)
    session.commit()
    log.info("benchmarks refreshed: %s",
             {r: d["samples"] for r, d in computed.items()})
    return computed


def load_effective_overrides(session: Session) -> tuple[dict, dict]:
    """(cs_benchmarks, vision_benchmarks) overlays for roles whose own-data
    sample count clears the threshold; empty dicts → seeds stay in charge."""
    cs: dict[str, dict[int, int]] = {}
    vision: dict[str, dict[str, float]] = {}
    for row in session.execute(select(ComputedBenchmark)).scalars():
        if row.samples < config.BENCHMARK_MIN_SAMPLES:
            continue
        data = row.data
        # UTILITY stays exempt from the CS heuristic even with own data
        if row.role != "UTILITY" and data.get("cs10") is not None and data.get("cs15") is not None:
            cs[row.role] = {10: data["cs10"], 15: data["cs15"]}
        vision[row.role] = {
            "wards_per_min": data["wards_per_min"],
            "control_wards": data["control_wards"],
        }
    return cs, vision
