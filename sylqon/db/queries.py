"""Common read queries against the v2 store.

Every function takes an explicit ``session`` so callers control its lifecycle
(and tests can pass a session bound to a temp database). Role filtering is done
in Python because SQLite's JSON containment operators are unreliable across
versions and the champion set is small (~170 rows).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from sylqon.db.schema import (
    Champion,
    ChampionBuild,
    ChampionCounter,
    ChampionSynergy,
    MatchHistory,
)


def ids_for_names(session: Session, names: list) -> list[int]:
    """Resolve a mixed list of champion display names and/or numeric Riot keys to
    DB champion ids. Unknown entries are silently dropped."""
    if not names:
        return []
    out: list[int] = []
    for n in names:
        champ = None
        if isinstance(n, int) or (isinstance(n, str) and n.isdigit()):
            champ = session.query(Champion).filter_by(riot_key=int(n)).first()
        if champ is None:
            champ = session.query(Champion).filter_by(name=str(n)).first()
        if champ is not None:
            out.append(champ.id)
    return out


def champions_for_role(session: Session, role: str) -> list[Champion]:
    """Every champion that can play ``role`` (per op.gg lane-meta, stored in
    ``Champion.roles``)."""
    return [c for c in session.query(Champion).all() if role in (c.roles or [])]


def counter_map(session: Session, champion_id: int, role: str,
                enemy_ids: list[int]) -> dict[int, float]:
    """``{enemy_id: advantage_score}`` for this champion in ``role`` vs the given
    enemies. Missing pairs are simply absent (callers treat them as neutral)."""
    if not enemy_ids:
        return {}
    rows = (
        session.query(ChampionCounter)
        .filter(
            ChampionCounter.champion_id == champion_id,
            ChampionCounter.role == role,
            ChampionCounter.counter_id.in_(enemy_ids),
        )
        .all()
    )
    return {r.counter_id: r.advantage_score for r in rows}


def synergy_map(session: Session, champion_id: int, role: str,
                ally_ids: list[int]) -> dict[int, float]:
    """``{ally_id: synergy_score}`` for this champion in ``role`` with the given
    allies."""
    if not ally_ids:
        return {}
    rows = (
        session.query(ChampionSynergy)
        .filter(
            ChampionSynergy.champion_id == champion_id,
            ChampionSynergy.role == role,
            ChampionSynergy.synergy_id.in_(ally_ids),
        )
        .all()
    )
    return {r.synergy_id: r.synergy_score for r in rows}


def build_for(session: Session, champion_id: int, role: str) -> ChampionBuild | None:
    return (
        session.query(ChampionBuild)
        .filter(ChampionBuild.champion_id == champion_id, ChampionBuild.role == role)
        .first()
    )


def meta_stats(session: Session, champion_id: int) -> dict:
    """``Champion.op_gg_stats`` (tier/win/pick) or ``{}`` if unknown."""
    champ = session.get(Champion, champion_id)
    return (champ.op_gg_stats or {}) if champ else {}


def recent_matches(session: Session, limit: int = 10) -> list[MatchHistory]:
    return (
        session.query(MatchHistory)
        .order_by(MatchHistory.played_at.desc())
        .limit(limit)
        .all()
    )
