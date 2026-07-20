"""Validate + normalize + upsert op.gg data into the v2 store.

Every function takes an explicit ``session`` (caller owns the transaction).
Champion resolution is by **display name** ("Miss Fortune"), which is what both
the op.gg MCP tools and ``Champion.name`` use.

Scoring-scale conventions (the scorer in Phase 3 consumes these):
  - ``Champion.op_gg_stats`` is keyed by role: ``{role: {tier, win_rate, pick_rate}}``
    with win/pick stored as **percentages** (op.gg returns fractions).
  - ``ChampionCounter.advantage_score`` in ``[-10, +10]`` (positive = subject
    counters the opponent).
  - ``ChampionSynergy.synergy_score`` in ``[0, 10]``.
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from sylqon.data import static
from sylqon.db.queries import build_for
from sylqon.db.schema import (
    Champion,
    ChampionBuild,
    ChampionCounter,
    ChampionSynergy,
    ProBuild,
)

log = logging.getLogger(__name__)


# -- scale mappings (heuristic; see module docstring) ------------------------
def winrate_pct(frac: float) -> float:
    """op.gg fraction (0.55) -> percentage (55.0)."""
    return round((frac or 0.0) * 100, 2)


def advantage_from_winrate(winner_winrate: float, favors_subject: bool) -> float:
    """Map a matchup win rate (fraction, >0.5 for the winning side) to a signed
    advantage in [-10, +10]. 50%->0, 55%->5, 60%+->10."""
    magnitude = max(0.0, min(10.0, ((winner_winrate or 0.0) - 0.5) * 100))
    return round(magnitude if favors_subject else -magnitude, 2)


def synergy_from_winrate(frac: float) -> float:
    """Map a pair win rate (fraction) to a synergy score in [0, 10].
    45%->0, 50%->5, 55%+->10. Pair win rates cluster tightly, so the floor is 45%."""
    return round(max(0.0, min(10.0, ((frac or 0.0) - 0.45) * 100)), 2)


def norm_role(position: str) -> str:
    """op.gg position vocab (adc/mid/support) -> normalized (bottom/middle/utility)."""
    return static.ROLE_ALIASES.get((position or "").lower().strip(), (position or "").lower().strip())


def _champ(session: Session, name: str) -> Champion | None:
    return session.query(Champion).filter_by(name=name).first()


# -- id-based upserts (used by the automated HTTP sync) ----------------------
def upsert_counter(session: Session, champion_id: int, counter_id: int,
                   role: str, advantage: float,
                   games: int | None = None, patch: str = "") -> None:
    row = session.get(ChampionCounter, (champion_id, counter_id, role))
    if row is None:
        row = ChampionCounter(champion_id=champion_id, counter_id=counter_id, role=role)
        session.add(row)
    row.advantage_score = advantage
    if games is not None:
        row.games = games
    if patch:
        row.patch = patch


def upsert_synergy(session: Session, champion_id: int, synergy_id: int,
                   role: str, score: float,
                   games: int | None = None, patch: str = "") -> None:
    row = session.get(ChampionSynergy, (champion_id, synergy_id, role))
    if row is None:
        row = ChampionSynergy(champion_id=champion_id, synergy_id=synergy_id, role=role)
        session.add(row)
    row.synergy_score = score
    if games is not None:
        row.games = games
    if patch:
        row.patch = patch


# -- lane meta (roles + tier/win/pick) ---------------------------------------
def ingest_lane_meta(session: Session, position: str, entries: list[dict]) -> dict:
    """Populate ``Champion.roles`` and per-role ``op_gg_stats`` from a lane-meta
    list. ``entries`` items: ``{champion, tier, win_rate, pick_rate}``."""
    role = norm_role(position)
    updated, unknown = 0, []
    for e in entries:
        champ = _champ(session, e.get("champion", ""))
        if champ is None:
            unknown.append(e.get("champion"))
            continue
        roles = list(champ.roles or [])
        if role not in roles:
            roles.append(role)
            champ.roles = roles  # reassign so SQLAlchemy detects the change
        stats = dict(champ.op_gg_stats or {})
        stats[role] = {
            "tier": e.get("tier"),
            "win_rate": winrate_pct(e.get("win_rate", 0.0)),
            "pick_rate": winrate_pct(e.get("pick_rate", 0.0)),
        }
        champ.op_gg_stats = stats
        build = build_for(session, champ.id, role)
        if build is not None:
            build.win_rate = stats[role]["win_rate"]
            build.pick_rate = stats[role]["pick_rate"]
        updated += 1
    session.flush()
    return {"role": role, "updated": updated, "unknown": [u for u in unknown if u]}


# -- counters ----------------------------------------------------------------
def ingest_counters(session: Session, champion: str, position: str,
                    strong_counters: list[dict], weak_counters: list[dict]) -> dict:
    """Upsert counter advantages for ``champion`` in ``position``.

    op.gg semantics: ``weak_counters`` = champions this champion beats (positive
    advantage); ``strong_counters`` = champions that beat it (negative). Each
    entry: ``{champion_name, win_rate}`` (win_rate is the winning side's rate)."""
    role = norm_role(position)
    me = _champ(session, champion)
    if me is None:
        return {"error": f"unknown champion {champion!r}"}

    count, unknown = 0, []

    def upsert(counter_name: str, advantage: float) -> None:
        nonlocal count
        other = _champ(session, counter_name)
        if other is None:
            unknown.append(counter_name)
            return
        row = session.get(ChampionCounter, (me.id, other.id, role))
        if row is None:
            row = ChampionCounter(champion_id=me.id, counter_id=other.id, role=role)
            session.add(row)
        row.advantage_score = advantage
        count += 1

    for e in weak_counters or []:
        upsert(e.get("champion_name", ""), advantage_from_winrate(e.get("win_rate", 0.0), True))
    for e in strong_counters or []:
        upsert(e.get("champion_name", ""), advantage_from_winrate(e.get("win_rate", 0.0), False))

    session.flush()
    return {"champion": champion, "role": role, "upserted": count,
            "unknown": [u for u in unknown if u]}


# -- synergies ---------------------------------------------------------------
def ingest_synergies(session: Session, champion: str, position: str,
                     synergies: list[dict]) -> dict:
    """Upsert ally synergies for ``champion`` in ``position``. Each entry:
    ``{synergy_champion_name, win_rate}``."""
    role = norm_role(position)
    me = _champ(session, champion)
    if me is None:
        return {"error": f"unknown champion {champion!r}"}

    count, unknown = 0, []
    for e in synergies or []:
        ally = _champ(session, e.get("synergy_champion_name", ""))
        if ally is None:
            unknown.append(e.get("synergy_champion_name"))
            continue
        row = session.get(ChampionSynergy, (me.id, ally.id, role))
        if row is None:
            row = ChampionSynergy(champion_id=me.id, synergy_id=ally.id, role=role)
            session.add(row)
        row.synergy_score = synergy_from_winrate(e.get("win_rate", 0.0))
        count += 1

    session.flush()
    return {"champion": champion, "role": role, "upserted": count,
            "unknown": [u for u in unknown if u]}


# -- pro / esports builds ----------------------------------------------------
def ingest_pro_build(session: Session, champion: str, position: str,
                     pro_name: str, build: dict, *, team: str = "",
                     region: str = "", patch: str = "", result: str = "") -> dict:
    """Upsert one pro player's build on ``champion``/``position``. Keyed by
    (champion, role, pro_name) so re-posting the same pro updates in place."""
    role = norm_role(position)
    champ = _champ(session, champion)
    if champ is None:
        return {"error": f"unknown champion {champion!r}"}
    if not pro_name:
        return {"error": "pro_name is required"}
    row = (session.query(ProBuild)
           .filter_by(champion_id=champ.id, role=role, pro_name=pro_name).first())
    if row is None:
        row = ProBuild(champion_id=champ.id, role=role, pro_name=pro_name)
        session.add(row)
    row.team, row.region, row.patch, row.result = team, region, patch, result
    row.build_json = build
    session.flush()
    return {"champion": champion, "role": role, "pro": pro_name, "ok": True}


def pro_builds_for(session: Session, champion: str, position: str = "") -> list[dict]:
    """Serialized pro builds for a champion (optionally a single role)."""
    champ = _champ(session, champion)
    if champ is None:
        return []
    q = session.query(ProBuild).filter(ProBuild.champion_id == champ.id)
    if position:
        q = q.filter(ProBuild.role == norm_role(position))
    out = []
    for r in q.order_by(ProBuild.created_at.desc()).all():
        out.append({
            "pro_name": r.pro_name, "team": r.team, "region": r.region,
            "role": r.role, "patch": r.patch, "result": r.result,
            "build": r.build_json or {},
        })
    return out


# -- build mirror (keeps the DB build table in sync with the live cache) -----
def mirror_build(session: Session, champion: str, role: str, build: dict,
                 source: str, patch: str) -> bool:
    """Mirror a converted build dict into ``ChampionBuild`` for browsing/variants.
    Returns False if the champion is unknown to the DB."""
    champ = _champ(session, champion)
    if champ is None:
        log.warning("mirror_build: unknown champion %r", champion)
        return False
    row = build_for(session, champ.id, role)
    if row is None:
        row = ChampionBuild(champion_id=champ.id, role=role)
        session.add(row)
    row.build_json = build
    row.source = source
    row.patch = patch
    row.updated_at = datetime.utcnow()
    session.flush()
    return True
