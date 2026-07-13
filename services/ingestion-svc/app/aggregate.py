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
from datetime import datetime, timedelta, timezone
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import config
from app.models import ComputedBenchmark, Match, PlayerRank, Timeline

log = logging.getLogger(__name__)

# Summoner's Rift queues: ranked solo, ranked flex, normal draft, normal blind.
SR_QUEUES = {420, 440, 400, 430}

ROLES = ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")

_BANDS = {
    "IRON": "iron-bronze", "BRONZE": "iron-bronze",
    "SILVER": "silver-gold", "GOLD": "silver-gold",
    "PLATINUM": "plat-emerald", "EMERALD": "plat-emerald",
    "DIAMOND": "diamond+", "MASTER": "diamond+",
    "GRANDMASTER": "diamond+", "CHALLENGER": "diamond+",
}


def band_for_tier(tier: str | None) -> str | None:
    return _BANDS.get((tier or "").upper())


def _cs_at(frames: list[dict], pid: int, minute: int) -> int | None:
    if len(frames) <= minute:
        return None
    pf = frames[minute].get("participantFrames", {}).get(str(pid))
    if pf is None:
        return None
    return int(pf.get("minionsKilled", 0)) + int(pf.get("jungleMinionsKilled", 0))


def compute_role_benchmarks(session: Session) -> dict[tuple[str, str], dict]:
    """Aggregate (role, band) medians over the newest ``BENCHMARK_SCAN_LIMIT``
    stored SR matches + timelines. Every sample lands in band "ALL"; ranked
    players additionally land in their tier band (player_ranks coverage grows
    with the seed crawl). Medians over a recent window are statistically ample
    and meta-fresher than all-history."""
    bands_by_puuid = {
        r.puuid: band_for_tier(r.tier)
        for r in session.execute(select(PlayerRank)).scalars()
    }
    samples: dict[tuple[str, str], dict[str, list[float]]] = {}

    def bucket(role: str, band: str) -> dict[str, list[float]]:
        return samples.setdefault(
            (role, band), {"cs10": [], "cs15": [], "wards_per_min": [], "control_wards": []}
        )

    # Streamed on a server-side cursor: without yield_per the driver buffers
    # every (raw + timeline) payload client-side — gigabytes at crawled-dataset
    # scale, which OOM-crash-looped both containers before these bounds.
    rows = session.execute(
        select(Match, Timeline)
        .join(Timeline, Timeline.match_id == Match.match_id)
        .where(Match.queue_id.in_(SR_QUEUES),
               Match.game_duration >= 16 * 60)  # remakes/stomps skew medians
        .order_by(Match.game_creation.desc().nullslast())
        .limit(config.BENCHMARK_SCAN_LIMIT)
        .execution_options(yield_per=50)
    )
    for match, timeline in rows:
        duration_min = (match.game_duration or 0) / 60
        frames = timeline.payload.get("frames", [])
        for p in match.raw.get("participants", []):
            role = p.get("teamPosition")
            pid = p.get("participantId")
            if role not in ROLES or not pid:
                continue
            targets = [bucket(role, "ALL")]
            band = bands_by_puuid.get(p.get("puuid"))
            if band:
                targets.append(bucket(role, band))
            cs10 = _cs_at(frames, pid, 10)
            cs15 = _cs_at(frames, pid, 15)
            for b in targets:
                if cs10 is not None:
                    b["cs10"].append(cs10)
                if cs15 is not None:
                    b["cs15"].append(cs15)
                b["wards_per_min"].append(p.get("wardsPlaced", 0) / duration_min)
                b["control_wards"].append(p.get("visionWardsBoughtInGame", 0))

    out: dict[tuple[str, str], dict] = {}
    for key, b in samples.items():
        n = len(b["wards_per_min"])
        if n == 0:
            continue
        out[key] = {
            "cs10": round(median(b["cs10"])) if b["cs10"] else None,
            "cs15": round(median(b["cs15"])) if b["cs15"] else None,
            "wards_per_min": round(median(b["wards_per_min"]), 2),
            "control_wards": round(median(b["control_wards"])),
            "samples": n,
        }
    return out


def _benchmarks_fresh(session: Session) -> bool:
    newest = session.execute(select(func.max(ComputedBenchmark.computed_at))).scalar()
    if newest is None:
        return False
    if newest.tzinfo is None:  # SQLite hands back naive datetimes
        newest = newest.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - newest
    return age < timedelta(minutes=config.BENCHMARK_REFRESH_MINUTES)


def refresh_benchmarks(session: Session, force: bool = False) -> dict[tuple[str, str], dict]:
    """Recompute and upsert the computed_benchmarks table.

    Throttled: the watcher calls this after every crawl cycle (~3 min), but
    medians move on the scale of patches — within ``BENCHMARK_REFRESH_MINUTES``
    of the last refresh this is a no-op returning ``{}`` unless ``force``d."""
    if not force and _benchmarks_fresh(session):
        return {}
    computed = compute_role_benchmarks(session)
    for (role, band), data in computed.items():
        row = session.get(ComputedBenchmark, (role, band)) or ComputedBenchmark(
            role=role, band=band
        )
        row.data = {k: v for k, v in data.items() if k != "samples"}
        row.samples = data["samples"]
        row.computed_at = datetime.now(timezone.utc)  # default fires on INSERT only
        session.add(row)
    session.commit()
    log.info("benchmarks refreshed: %s",
             {f"{r}/{b}": d["samples"] for (r, b), d in computed.items()})
    return computed


def load_effective_overrides(session: Session, band: str | None = None) -> tuple[dict, dict]:
    """(cs_benchmarks, vision_benchmarks) overlays. Per role, the player's
    rank band wins if it clears the threshold, then "ALL", else the seed
    stays in charge (role simply absent from the returned dicts)."""
    best: dict[str, ComputedBenchmark] = {}
    for row in session.execute(select(ComputedBenchmark)).scalars():
        if row.samples < config.BENCHMARK_MIN_SAMPLES:
            continue
        current = best.get(row.role)
        if row.band == band or (current is None and row.band == "ALL"):
            if current is None or row.band == band:
                best[row.role] = row

    cs: dict[str, dict[int, int]] = {}
    vision: dict[str, dict[str, float]] = {}
    for role, row in best.items():
        data = row.data
        # UTILITY stays exempt from the CS heuristic even with own data
        if role != "UTILITY" and data.get("cs10") is not None and data.get("cs15") is not None:
            cs[role] = {10: data["cs10"], 15: data["cs15"]}
        vision[role] = {
            "wards_per_min": data["wards_per_min"],
            "control_wards": data["control_wards"],
        }
    return cs, vision
