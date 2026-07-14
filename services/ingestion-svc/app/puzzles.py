"""Daily Draft puzzle generation + lookup — the engine behind /daily.

A puzzle is one real stored SR match frozen before one pick: the solver sees
their four teammates and all five enemies, and picks the hidden champion from
six candidates. Everything the page needs is pre-computed at generation time
with the deterministic draft engine (``app.draftintel``) plus our own
lane-matchup aggregation, then stored as one JSON payload — serving is a
single row read, and the recorded analysis never shifts as the dataset grows.

Guardrails baked in (see docs/WEB_DRAFT_TERV.md §6):
- **Anonymous**: the payload carries champions only — no puuid, no player
  names; the match_id stays on the row (dedupe) and is never rendered.
- **No skill-scores**: every ``win_pct`` is the [35, 65]-clamped comp
  heuristic; candidate tiers grade the *answer options* ("strong / solid /
  risky"), never players, and several answers can share a tier — the framing
  is "the engine's reading + what actually happened", not "the correct pick".
- **Deterministic**: the RNG is seeded with the puzzle date, so a re-run on
  the same dataset reproduces the same puzzle; curation = regenerate with
  ``python -m app.cli puzzle-gen --date YYYY-MM-DD --replace``, which is
  guaranteed to freeze a *different* match (used matches are excluded).
"""
from __future__ import annotations

import hashlib
import logging
import random
from datetime import date as _date
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import config, draftintel
from app.builds import SR_QUEUES, champion_matchups
from app.models import DailyPuzzle, Match, MatchParticipant, PlayerRank

log = logging.getLogger(__name__)

PUZZLE_SCHEMA = 1
ROLES = ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")
ROLE_LABELS = {"TOP": "Top", "JUNGLE": "Jungle", "MIDDLE": "Mid",
               "BOTTOM": "Bot", "UTILITY": "Support"}
QUEUE_LABELS = {420: "Ranked Solo/Duo", 440: "Ranked Flex",
                400: "Normal Draft", 430: "Normal Blind"}
CANDIDATE_COUNT = 6
_TIER_LADDER = ("IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD",
                "DIAMOND", "MASTER", "GRANDMASTER", "CHALLENGER")


class PuzzleNotPossible(Exception):
    """No stored match can currently be frozen into a six-candidate puzzle."""


def _rng(date_iso: str) -> random.Random:
    return random.Random(hashlib.sha256(f"sylqon-daily:{date_iso}".encode()).hexdigest())


def _role_for(date_iso: str) -> str:
    """Roles rotate by calendar day so regulars get variety across the week."""
    return ROLES[_date.fromisoformat(date_iso).toordinal() % len(ROLES)]


# -- match selection -------------------------------------------------------------
def _eligible_matches(session: Session, exclude: set[str]) -> list:
    """Newest SR matches worth freezing — typed columns only (the raw JSONB
    stays untouched; unbounded Match scans OOM-killed this service once)."""
    rows = session.execute(
        select(Match.match_id, Match.patch, Match.queue_id, Match.game_duration)
        .where(Match.queue_id.in_(SR_QUEUES),
               Match.game_duration >= config.PUZZLE_MIN_DURATION_S)
        .order_by(Match.game_creation.desc().nullslast())
        .limit(config.PUZZLE_SELECT_WINDOW)
    ).all()
    return [r for r in rows if r.match_id not in exclude]


def _draft_of(session: Session, match_id: str) -> dict | None:
    """{team_id: {role: participant}} for a well-formed 5v5 draft, else None.

    Well-formed: ten participants, both teams cover all five roles exactly
    once, every champion resolves in the draft bundle, no duplicate champion
    anywhere in the match."""
    parts = session.execute(
        select(MatchParticipant).where(MatchParticipant.match_id == match_id)
    ).scalars().all()
    if len(parts) != 10:
        return None
    by_team: dict = {}
    names = set()
    for p in parts:
        ident = draftintel.identity(p.champion_name)
        if (ident is None or p.team_position not in ROLES
                or p.team_id not in (100, 200)):
            return None
        names.add(ident["name"])
        if p.team_position in by_team.setdefault(p.team_id, {}):
            return None
        by_team[p.team_id][p.team_position] = p
    if set(by_team) != {100, 200} or len(names) != 10:
        return None
    for team in by_team.values():
        if set(team) != set(ROLES):
            return None
    return by_team


def _rank_band(session: Session, puuids: list[str]) -> str | None:
    """Highest known solo-queue tier among the ten players (League-V4 cache) —
    a descriptive context label ("seen in EMERALD"), never a score."""
    tiers = session.execute(
        select(PlayerRank.tier).where(PlayerRank.puuid.in_(puuids))
    ).scalars().all()
    known = [t for t in tiers if t in _TIER_LADDER]
    return max(known, key=_TIER_LADDER.index) if known else None


# -- candidate analysis ------------------------------------------------------------
def _lane_records(session: Session, opponent_slug: str, role: str) -> dict:
    """{canonical display name: (games, winrate_pct)} of champions that laned
    against the opponent in this role — from our own aggregation. The
    ``champion_matchups`` winrate is the *anchor's* (the opponent's), so it is
    inverted here to the candidate's side."""
    records = {}
    for name, games, opp_wr in champion_matchups(session, opponent_slug, role):
        ident = draftintel.identity(name)
        if ident:
            records[ident["name"]] = (games, 100 - opp_wr)
    return records


def _role_top(session: Session, role: str, limit: int = 30) -> list[str]:
    """Most-played champions in a role across the stored dataset (canonical
    display names) — the candidate-pool fallback when matchup rows are thin."""
    rows = session.execute(
        select(MatchParticipant.champion_name, func.count())
        .join(Match, Match.match_id == MatchParticipant.match_id)
        .where(Match.queue_id.in_(SR_QUEUES),
               MatchParticipant.team_position == role,
               MatchParticipant.champion_name.isnot(None))
        .group_by(MatchParticipant.champion_name)
        .order_by(func.count().desc())
        .limit(limit)
    ).all()
    out = []
    for name, _count in rows:
        ident = draftintel.identity(name)
        if ident and ident["name"] not in out:
            out.append(ident["name"])
    return out


def _analyze(name: str, ally_names: list[str], enemy_names: list[str],
             lane: tuple[int, int] | None) -> dict:
    """Fold one candidate into the ally team and read the resulting draft.
    ``lane`` is (games, winrate_pct) vs the lane opponent from our own data;
    the winrate maps onto the engine's roughly [-10, 10] lane-edge scale as
    (wr - 50) * 0.2, so a 60% lane record folds in as +2.0."""
    ally = [draftintel.profile_by_name(n) for n in ally_names] + \
           [draftintel.profile_by_name(name)]
    enemy = [draftintel.profile_by_name(n) for n in enemy_names]
    ally_comp = draftintel.classify_comp(ally)
    enemy_comp = draftintel.classify_comp(enemy)
    lane_advantage = (lane[1] - 50) * 0.2 if lane else None
    balance = draftintel.draft_balance(
        ally_comp, enemy_comp,
        draftintel.summarize_team(ally), draftintel.summarize_team(enemy),
        lane_advantage=lane_advantage)
    return {"balance": balance, "ally_archetype": ally_comp["label"]}


def _tier(win_pct: int, best_pct: int) -> str:
    """Band the answer options relative to the best engine read — several
    candidates can (and often do) share a band; there is no single "correct"
    answer, only stronger and riskier reads."""
    diff = best_pct - win_pct
    if diff <= 1:
        return "strong"
    if diff <= 4:
        return "solid"
    return "risky"


# -- puzzle assembly ------------------------------------------------------------
def _freeze(session: Session, rng: random.Random, match_row, by_team: dict,
            side: int, role: str) -> dict:
    other = 200 if side == 100 else 100
    hidden = by_team[side][role]
    opponent = by_team[other][role]
    ally_parts = [by_team[side][r] for r in ROLES if r != role]
    enemy_parts = [by_team[other][r] for r in ROLES]

    real = draftintel.identity(hidden.champion_name)["name"]
    ally_names = [draftintel.identity(p.champion_name)["name"] for p in ally_parts]
    enemy_names = [draftintel.identity(p.champion_name)["name"] for p in enemy_parts]
    in_draft = set(ally_names) | set(enemy_names) | {real}

    lane_records = _lane_records(session, opponent.champion_name, role)
    matchup_pool = [n for n in lane_records if n not in in_draft]
    matchup_pool.sort(key=lambda n: (-lane_records[n][0], n))  # most-played first
    fallback = [n for n in _role_top(session, role) if n not in in_draft]

    pool = [real]
    for name in matchup_pool + fallback:
        if len(pool) >= config.PUZZLE_CANDIDATE_POOL + 1:
            break
        if name not in pool:
            pool.append(name)
    if len(pool) < CANDIDATE_COUNT:
        raise PuzzleNotPossible(
            f"only {len(pool)} candidates for {role} vs {opponent.champion_name}")

    analyses = {n: _analyze(n, ally_names, enemy_names, lane_records.get(n))
                for n in pool}
    engine_top = min(
        pool, key=lambda n: (-analyses[n]["balance"]["win_pct"],
                             -lane_records.get(n, (0, 0))[0], n))

    chosen = [real]
    if engine_top != real:
        chosen.append(engine_top)
    for name in pool[1:]:
        if len(chosen) >= CANDIDATE_COUNT:
            break
        if name not in chosen:
            chosen.append(name)
    if len(chosen) < CANDIDATE_COUNT:
        raise PuzzleNotPossible("candidate pool collapsed below six")

    best_pct = max(analyses[n]["balance"]["win_pct"] for n in chosen)
    candidates = []
    for name in chosen:
        analysis = analyses[name]
        lane = lane_records.get(name)
        candidates.append({
            **draftintel.identity(name),
            "tier": _tier(analysis["balance"]["win_pct"], best_pct),
            "balance": analysis["balance"],
            "ally_archetype": analysis["ally_archetype"],
            "lane": {"games": lane[0], "winrate_pct": lane[1]} if lane else None,
            "is_real": name == real,
            "is_engine_top": name == engine_top,
        })
    rng.shuffle(candidates)

    stats = hidden.stats or {}
    enemy_comp = draftintel.classify_comp(
        [draftintel.profile_by_name(n) for n in enemy_names])
    return {
        "schema": PUZZLE_SCHEMA,
        "match": {
            "patch": match_row.patch or "",
            "queue_id": match_row.queue_id,
            "duration_min": round((match_row.game_duration or 0) / 60),
            "rank_band": _rank_band(
                session, [p.puuid for team in by_team.values() for p in team.values()]),
        },
        "role": role,
        "role_label": ROLE_LABELS[role],
        "side": "blue" if side == 100 else "red",
        "ally": [draftintel.identity(p.champion_name) for p in ally_parts],
        "enemy": [draftintel.identity(p.champion_name) for p in enemy_parts],
        "enemy_comp": enemy_comp,
        "candidates": candidates,
        "epilogue": {
            **draftintel.identity(hidden.champion_name),
            "win": bool(hidden.win),
            "kills": hidden.kills or 0,
            "deaths": hidden.deaths or 0,
            "assists": hidden.assists or 0,
            "cs": (hidden.total_minions_killed or 0) + (hidden.neutral_minions_killed or 0),
            "items": [stats.get(f"item{i}") for i in range(6) if stats.get(f"item{i}")],
        },
    }


def build_puzzle(session: Session, date_iso: str) -> tuple[str, dict]:
    """Freeze a puzzle for a date without persisting it. Deterministic per
    (date, dataset). Returns (match_id, payload)."""
    rng = _rng(date_iso)
    used = set(session.execute(select(DailyPuzzle.match_id)).scalars())
    eligible = _eligible_matches(session, used)
    if not eligible:
        raise PuzzleNotPossible("no eligible stored SR match")
    role = _role_for(date_iso)
    rng.shuffle(eligible)
    for match_row in eligible[:config.PUZZLE_TRIES]:
        by_team = _draft_of(session, match_row.match_id)
        if by_team is None:
            continue
        side = rng.choice((100, 200))
        try:
            payload = _freeze(session, rng, match_row, by_team, side, role)
        except PuzzleNotPossible as exc:
            log.debug("puzzle skip %s: %s", match_row.match_id, exc)
            continue
        return match_row.match_id, payload
    raise PuzzleNotPossible(
        f"no well-formed draft in the newest {config.PUZZLE_TRIES} tried matches")


def generate_for_date(session: Session, date_iso: str, *,
                      replace: bool = False) -> tuple[dict, bool]:
    """Get-or-create the puzzle row for a date; ``replace`` regenerates onto a
    different match (the current one stays in the exclusion set). Returns
    (payload, created_or_replaced)."""
    existing = session.get(DailyPuzzle, date_iso)
    if existing is not None and not replace:
        return existing.payload, False
    match_id, payload = build_puzzle(session, date_iso)
    if existing is not None:
        existing.match_id = match_id
        existing.payload = payload
        existing.generated_at = datetime.now(timezone.utc)
    else:
        session.add(DailyPuzzle(puzzle_date=date_iso, match_id=match_id,
                                payload=payload))
    session.commit()
    return payload, True


def get_puzzle(session: Session, date_iso: str) -> dict | None:
    row = session.get(DailyPuzzle, date_iso)
    return row.payload if row else None


def recent_dates(session: Session, before: str, limit: int = 30) -> list[str]:
    """Puzzle dates strictly before a date, newest first — the /daily archive
    never leaks a future (pre-generated) puzzle."""
    return list(session.execute(
        select(DailyPuzzle.puzzle_date)
        .where(DailyPuzzle.puzzle_date < before)
        .order_by(DailyPuzzle.puzzle_date.desc())
        .limit(limit)
    ).scalars())
