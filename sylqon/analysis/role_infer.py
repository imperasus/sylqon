"""Enemy role inference for champ select (deterministic, DB-only, no LLM).

Riot's champ-select session exposes ``assignedPosition`` for our OWN team but
almost never for the enemy team, so every downstream layer that needs the
*lane opponent* — :mod:`sylqon.analysis.lane_counter` (first-back items, lane
directives, matchup starter) and :mod:`sylqon.analysis.matchup` (the post-lock
lane scorecard) — silently degrades to nothing in real solo-queue games.

This module reconstructs the missing roles. Each revealed champion carries a
per-role prior from op.gg lane-meta pick-rate (``Champion.op_gg_stats``); we
then solve a **max-weight assignment** of champions to the five canonical roles
so the whole team is read jointly (a champion that could flex top/support is
pulled to whichever role the rest of the team leaves open). Champions whose real
``assignedPosition`` IS known are pinned as hard constraints.

Pure and network-free; the assignment core (:func:`assign_roles`) takes plain
dicts so it is fully unit-testable without a DB.
"""
from __future__ import annotations

import logging
from itertools import permutations

log = logging.getLogger(__name__)

ROLES: tuple[str, ...] = ("top", "jungle", "middle", "bottom", "utility")

# Below this winning-role share we treat the read as a genuine flex (ambiguous
# lane) — callers should widen rather than commit to a single lane opponent.
FLEX_CONFIDENCE = 0.55


def assign_roles(candidates: list[dict]) -> dict:
    """Solve the champion→role assignment.

    ``candidates``: ``[{"key", "weights": {role: float}, "pin": role | None}]``
    where ``weights`` is a per-role prior (need not be normalized) and ``pin``
    forces a role (a known ``assignedPosition``). Returns
    ``{key: (role, confidence)}`` where ``confidence`` in [0, 1] is the assigned
    role's share of that champion's total prior mass (1.0 for a pinned role).

    Deterministic: with ≤5 free champions over ≤5 roles the assignment space is
    at most 5! = 120, so we brute-force the exact optimum (no scipy)."""
    pinned: dict = {}
    used: set[str] = set()
    free: list[dict] = []
    for c in candidates:
        pin = c.get("pin")
        if pin in ROLES and pin not in used:
            pinned[c["key"]] = pin
            used.add(pin)
        else:
            free.append(c)

    avail = [r for r in ROLES if r not in used]
    free = free[:len(avail)]  # cap — a normal team never exceeds 5 per side

    result: dict = {k: (r, 1.0) for k, r in pinned.items()}
    if not free:
        return result

    best_perm, best_score = None, -1.0
    for perm in permutations(avail, len(free)):
        # Tie-break deterministically: permutations() yields a stable order, and
        # we only replace on a STRICT improvement, so the first (lexicographically
        # smallest) optimum wins — stable across runs.
        score = sum(free[i]["weights"].get(perm[i], 0.0) for i in range(len(free)))
        if score > best_score:
            best_score, best_perm = score, perm

    for i, c in enumerate(free):
        role = best_perm[i]
        total = sum(c["weights"].values()) or 1.0
        conf = c["weights"].get(role, 0.0) / total
        result[c["key"]] = (role, round(conf, 3))
    return result


def _role_weights(op_gg_stats: dict | None, roles: list | None) -> dict:
    """Per-role prior for one champion. Pick-rate across the champion's viable
    lanes is the primary signal; fall back to a flat prior over its known roles,
    then to a tiny flat prior over all roles so an unknown champion still gets
    assigned *something* rather than blocking the solve."""
    stats = op_gg_stats or {}
    weights = {r: float((stats.get(r) or {}).get("pick_rate") or 0.0) for r in ROLES}
    if sum(weights.values()) > 0:
        return weights
    known = [r for r in (roles or []) if r in ROLES]
    if known:
        return {r: 1.0 for r in known}
    return {r: 0.01 for r in ROLES}


def infer_enemy_roles(session, picks: list) -> dict:
    """``{champion_id: (role, confidence)}`` for the given ``ChampPick`` list.

    Reads each champion's op.gg lane-meta prior from the DB and solves the joint
    assignment. Best-effort: on any DB failure returns ``{}`` so callers keep
    the prior (empty-role) behaviour. A pick that already has a real role is
    pinned so inference never overrides ground truth."""
    picks = [p for p in picks if getattr(p, "champion_id", 0)]
    if not picks:
        return {}
    try:
        from sylqon.db.schema import Champion
        names = [p.name for p in picks]
        rows = {c.name: c for c in session.query(Champion)
                .filter(Champion.name.in_(names)).all()}
    except Exception:  # pragma: no cover - defensive
        log.debug("role inference DB lookup failed", exc_info=True)
        return {}

    candidates = []
    for p in picks:
        row = rows.get(p.name)
        candidates.append({
            "key": p.champion_id,
            "weights": _role_weights(getattr(row, "op_gg_stats", None),
                                     getattr(row, "roles", None)),
            "pin": p.role if p.role in ROLES else None,
        })
    return assign_roles(candidates)


def enrich_roles(session, picks: list) -> int:
    """Fill in missing ``role`` on each pick from inference, in place. Never
    touches a pick that already has a role. Returns the number of roles filled
    (0 when nothing was inferred / DB unavailable)."""
    missing = [p for p in picks if not getattr(p, "role", "")]
    if not missing:
        return 0
    inferred = infer_enemy_roles(session, picks)
    filled = 0
    for p in missing:
        got = inferred.get(p.champion_id)
        if got:
            p.role = got[0]
            filled += 1
    return filled
