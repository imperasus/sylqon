"""Champion-pool coverage analysis — the Phase 2 (S3) core.

Per role, a player's pool is scored on three axes (roadmap §5.1):

- **performance** — the player's own win rate on their played champions,
  shrunk toward neutral by sample size (few games ≈ weak evidence);
- **blind_safety** — how safely the pool's champions can be picked before
  the opponent reveals theirs: the worst lane-matchup win rate observed in
  our own Match-V5 aggregation (a champ with no bad matchup is blind-safe);
- **counter_coverage** — against the champions most present in our dataset
  for that role, does *some* champ in the pool hold at least an even lane
  record?

All statistics come from our own stored matches (official Riot API data,
no scraping). Every component is honesty-gated: below the minimum sample
count it reports neutral 50 and flags ``low_data`` instead of inventing
confidence. Deliberate ToS framing: these numbers measure *pool coverage*,
never player skill — no MMR/ELO-like language anywhere.
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Match, MatchParticipant

log = logging.getLogger(__name__)

SR_QUEUES = {420, 440, 400, 430}
ROLES = ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")

MIN_MATCHUP_GAMES = 2    # a lane pairing below this many games is ignored
MIN_POPULAR_GAMES = 3    # a champ below this presence isn't a "threat" yet
MIN_SUGGEST_GAMES = 5    # dataset presence needed to be *suggested* (unless played)
MIN_BLIND_OPPONENTS = 2  # distinct opponents needed before "blind-safe" is claimed
TOP_THREATS = 8          # how many popular enemies counter-coverage checks
POOL_SIZE = 3


# ── dataset extraction (one pass over stored matches) ─────────────────────────


def role_dataset(session: Session, role: str) -> dict:
    """Aggregate per-role stats from every stored SR match.

    Returns ``{"champs": {name: [games, wins]}, "matchups": {(a, b): [games,
    a_wins]}}`` where matchup keys are directed (a's record against b) and
    names keep their display casing from the data.
    """
    champs: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    matchups: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])

    for match in session.execute(select(Match)).scalars():
        if match.queue_id not in SR_QUEUES:
            continue
        laners = [
            p for p in match.raw.get("participants", [])
            if p.get("teamPosition") == role and p.get("championName")
        ]
        for p in laners:
            entry = champs[p["championName"]]
            entry[0] += 1
            entry[1] += 1 if p.get("win") else 0
        if len(laners) == 2 and laners[0].get("teamId") != laners[1].get("teamId"):
            a, b = laners
            ma = matchups[(a["championName"], b["championName"])]
            ma[0] += 1
            ma[1] += 1 if a.get("win") else 0
            mb = matchups[(b["championName"], a["championName"])]
            mb[0] += 1
            mb[1] += 1 if b.get("win") else 0
    return {"champs": dict(champs), "matchups": dict(matchups)}


def player_role_stats(session: Session, puuid: str) -> dict[str, dict[str, list[int]]]:
    """{role: {champ: [games, wins]}} for the player's stored SR matches."""
    out: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    rows = session.execute(
        select(MatchParticipant, Match.queue_id)
        .join(Match, Match.match_id == MatchParticipant.match_id)
        .where(MatchParticipant.puuid == puuid)
    )
    for participant, queue_id in rows:
        if queue_id not in SR_QUEUES:
            continue
        role = participant.team_position
        if role not in ROLES or not participant.champion_name:
            continue
        entry = out[role][participant.champion_name]
        entry[0] += 1
        entry[1] += 1 if participant.win else 0
    return {r: dict(c) for r, c in out.items()}


# ── component scores (0–100, honesty-gated) ──────────────────────────────────


def _shrunk_wr(games: int, wins: int, prior_games: int = 3) -> float:
    """Win rate shrunk toward 50% by sample size — 2/2 is not '100% WR'."""
    return (wins + 0.5 * prior_games) / (games + prior_games) * 100


def performance_score(pool_stats: dict[str, list[int]]) -> tuple[int, bool]:
    """Games-weighted shrunk win rate across the player's pool."""
    total = sum(g for g, _ in pool_stats.values())
    if total == 0:
        return 50, True
    weighted = sum(
        _shrunk_wr(g, w) * g for g, w in pool_stats.values()
    ) / total
    return round(weighted), total < 5


def _matchup_evidence(
    champ: str, matchups: dict[tuple[str, str], list[int]]
) -> list[tuple[str, int, float]]:
    """Qualifying (opponent, games, shrunk_wr) samples for a champion. WRs are
    sample-shrunk so a 0/2 lane reads as 25%, not an absolute 0%."""
    out = []
    for (a, b), (games, wins) in matchups.items():
        if a == champ and games >= MIN_MATCHUP_GAMES:
            out.append((b, games, _shrunk_wr(games, wins, prior_games=2)))
    return out


def blind_safety_score(
    pool: list[str], matchups: dict[tuple[str, str], list[int]]
) -> tuple[int, bool]:
    """Best champ's worst-matchup WR: can you first-pick *something* safely?
    A champion only counts once it has evidence against MIN_BLIND_OPPONENTS
    distinct opponents — "no bad matchup found" is not the same as safe."""
    best = None
    for champ in pool:
        evidence = _matchup_evidence(champ, matchups)
        if len(evidence) < MIN_BLIND_OPPONENTS:
            continue
        worst = min(wr for _, _, wr in evidence)
        best = worst if best is None else max(best, worst)
    if best is None:
        return 50, True
    return round(best), False


def counter_coverage_score(
    pool: list[str],
    champs: dict[str, list[int]],
    matchups: dict[tuple[str, str], list[int]],
) -> tuple[int, bool, list[str]]:
    """Share of the role's most-present champions that some pool member holds
    an even-or-better lane record against. Returns (score, low_data, uncovered)."""
    threats = [
        name
        for name, (games, _) in sorted(champs.items(), key=lambda kv: -kv[1][0])
        if games >= MIN_POPULAR_GAMES and name not in pool
    ][:TOP_THREATS]
    if not threats:
        return 50, True, []
    covered, uncovered, judged = 0, [], 0
    for threat in threats:
        verdicts = []
        for champ in pool:
            games, wins = matchups.get((champ, threat), (0, 0))
            if games >= MIN_MATCHUP_GAMES:
                verdicts.append(_shrunk_wr(games, wins, prior_games=2))
        if not verdicts:
            continue  # no evidence either way — don't count against the pool
        judged += 1
        if max(verdicts) >= 50:
            covered += 1
        else:
            uncovered.append(threat)
    if judged == 0:
        return 50, True, []
    return round(covered / judged * 100), judged < 3, uncovered


# ── pool suggestion (greedy) ─────────────────────────────────────────────────


def _candidate_score(
    champ: str,
    personal: dict[str, list[int]],
    champs: dict[str, list[int]],
    matchups: dict[tuple[str, str], list[int]],
) -> tuple[float, list[str]]:
    reasons: list[str] = []
    g, w = personal.get(champ, (0, 0))
    comfort = _shrunk_wr(g, w) if g else 50.0
    if g >= 3 and w / g >= 0.55:
        reasons.append("comfort")
    dg, dw = champs.get(champ, (0, 0))
    dataset_wr = _shrunk_wr(dg, dw, prior_games=5) if dg else 50.0
    safety, safety_low = blind_safety_score([champ], matchups)
    if not safety_low and safety >= 50:
        reasons.append("blind-safe")
    score = 0.45 * comfort + 0.30 * dataset_wr + 0.25 * safety
    return score, reasons


def suggest_pool(
    personal: dict[str, list[int]],
    champs: dict[str, list[int]],
    matchups: dict[tuple[str, str], list[int]],
) -> list[dict]:
    # Champions the player already plays are always candidates; unplayed ones
    # need real dataset presence before we'd recommend learning them.
    candidates = set(personal) | {
        name for name, (g, _) in champs.items() if g >= MIN_SUGGEST_GAMES
    }
    if not candidates:
        return []
    scored = {
        champ: _candidate_score(champ, personal, champs, matchups)
        for champ in candidates
    }

    picked: list[dict] = []

    # Comfort anchor: the player's most-played champ with a winning record
    # leads the suggestion — the pool is built around it, not instead of it.
    anchor = max(
        (c for c, (g, w) in personal.items() if g >= 3 and w / g >= 0.5),
        key=lambda c: personal[c][0],
        default=None,
    )
    if anchor is not None and anchor in scored:
        _, reasons = scored.pop(anchor)
        if "comfort" not in reasons:
            reasons = ["comfort", *reasons]
        g, w = personal[anchor]
        picked.append(
            {"champion": anchor, "reasons": reasons, "personal": {"games": g, "wins": w}}
        )

    while len(picked) < POOL_SIZE and scored:
        pool_now = [p["champion"] for p in picked]
        best_name, best_val, best_reasons = None, -1.0, []
        for champ, (base, reasons) in scored.items():
            cov_before, _, _ = counter_coverage_score(pool_now, champs, matchups)
            cov_after, _, _ = counter_coverage_score(pool_now + [champ], champs, matchups)
            marginal = max(0, cov_after - cov_before)
            value = base + 0.35 * marginal
            if value > best_val:
                best_name, best_val = champ, value
                best_reasons = reasons + (["covers-gaps"] if marginal >= 15 else [])
        g, w = personal.get(best_name, (0, 0))
        picked.append(
            {
                "champion": best_name,
                "reasons": best_reasons or ["meta-presence"],
                "personal": {"games": g, "wins": w} if g else None,
            }
        )
        scored.pop(best_name)
    return picked


# ── top-level analysis ────────────────────────────────────────────────────────


def analyze_pool(session: Session, puuid: str) -> dict | None:
    """Full per-role pool-coverage report for a player. None → no stored games."""
    per_role = player_role_stats(session, puuid)
    if not per_role:
        return None
    roles_out: dict[str, dict] = {}
    for role, personal in sorted(
        per_role.items(), key=lambda kv: -sum(g for g, _ in kv[1].values())
    ):
        data = role_dataset(session, role)
        pool = sorted(personal, key=lambda c: -personal[c][0])
        perf, perf_low = performance_score(personal)
        safety, safety_low = blind_safety_score(pool, data["matchups"])
        coverage, cov_low, uncovered = counter_coverage_score(
            pool, data["champs"], data["matchups"]
        )
        score = round(0.4 * perf + 0.3 * safety + 0.3 * coverage)
        roles_out[role] = {
            "games": sum(g for g, _ in personal.values()),
            "current": [
                {"champion": c, "games": g, "wins": w}
                for c, (g, w) in sorted(personal.items(), key=lambda kv: -kv[1][0])
            ],
            "coverage_score": score,
            "components": {
                "performance": perf,
                "blind_safety": safety,
                "counter_coverage": coverage,
            },
            "low_data": perf_low or safety_low or cov_low,
            "suggested": suggest_pool(personal, data["champs"], data["matchups"]),
            "uncovered": uncovered,
        }
    return {"puuid": puuid, "roles": roles_out}
