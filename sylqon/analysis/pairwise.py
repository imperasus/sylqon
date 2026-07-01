"""Per-pair counter / synergy ranking for the live champ-select board.

Given a single revealed pick — an enemy to counter, or an ally to synergise
with — and a set of candidate champions, rank those candidates for that one
matchup. The caller supplies the candidates (the live board passes the whole role
roster, so the suggestion is the best answer overall, not just from the player's
pool). Two deterministic signals are blended:

  * a **tag heuristic floor** — reuses the engage / frontline / enchanter /
    threat / damage predicates from the champion recommender (``ai.pick_prompt``)
    so a sensible ranking exists with no database and no Ollama; it also yields
    the short reason badges shown in the UI;
  * an optional **op.gg pairwise booster** — when a DB session is supplied and
    the champion-counter / champion-synergy tables are populated (after a full
    op.gg sync), the real ``advantage_score`` / ``synergy_score`` for the exact
    pair is folded in and surfaced as a numeric edge.

Network-free and Ollama-free, mirroring ``analysis.draft_intel``. Every function
accepts either a ``lobby.ChampPick`` or the plain dict shape
``{"name", "slug", "tags", "threats", "damage_type"}`` so callers can score
synthesised picks without building a full dataclass.
"""
from __future__ import annotations

import logging

from sylqon.ai.pick_prompt import (
    _is_enchanter,
    _is_engage,
    _is_frontline,
    _pick_threats,
    _tags,
)
from sylqon.db import queries

log = logging.getLogger(__name__)

# How strongly real op.gg matchup data tilts the tag-heuristic floor. Counter
# advantage is [-10, +10] -> [-3, +3]; synergy is [0, 10] centred on 5 -> [-2, +2].
DB_COUNTER_WEIGHT = 0.3
DB_SYNERGY_WEIGHT = 0.4


# -- shape-agnostic accessors -----------------------------------------------
def _name(p) -> str:
    return p["name"] if isinstance(p, dict) else p.name


def _slug(p) -> str:
    return p.get("slug", "") if isinstance(p, dict) else ""


def _damage(p) -> str:
    return p["damage_type"] if isinstance(p, dict) else p.damage_type


def _dedup(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


# -- one-vs-one tag heuristics ----------------------------------------------
def score_candidate_into_enemy(cand, enemy) -> tuple[int, list[str]]:
    """How well ``cand`` (a pool champion) fares into one ``enemy`` pick, read
    from class tags + threat flags. Returns ``(score, reason_badges)`` where the
    badges are short, positive, UI-ready labels."""
    c_tags = _tags(cand)
    e_tags = _tags(enemy)
    e_threats = _pick_threats(enemy)
    enemy_squishy_carry = bool(e_tags & {"Marksman", "Mage"}) and not _is_frontline(enemy)
    score = 0
    reasons: list[str] = []

    if ("tank" in e_threats or "Tank" in e_tags) and "Marksman" in c_tags:
        score += 2
        reasons.append("Anti-Tank")
    if (e_threats & {"burst_ad", "burst_ap"}) and _is_frontline(cand):
        score += 2
        reasons.append("Safe Into Burst")
    if enemy_squishy_carry and _is_engage(cand):
        score += 2
        reasons.append("Engage")
    if "poke" in e_threats and _is_engage(cand):
        score += 2
        reasons.append("Engage")
    if "heavy_cc" in e_threats and _is_frontline(cand):
        score += 1
        reasons.append("Frontline")
    return score, _dedup(reasons)


def score_candidate_with_ally(cand, ally) -> tuple[int, list[str]]:
    """How well ``cand`` synergises with one locked ``ally``. Returns
    ``(score, reason_badges)``."""
    c_tags = _tags(cand)
    a_tags = _tags(ally)
    score = 0
    reasons: list[str] = []

    if _is_engage(ally) and (c_tags & {"Marksman", "Mage"}):
        score += 2
        reasons.append("Cash-in Engage")
    if _is_enchanter(ally) and (c_tags & {"Marksman", "Mage"}):
        score += 2
        reasons.append("Peel Target")
    if "Marksman" in a_tags and _is_enchanter(cand):
        score += 2
        reasons.append("Peel")
    if "Marksman" in a_tags and _is_engage(cand):
        score += 2
        reasons.append("Engage")
    if not _is_frontline(ally) and _is_frontline(cand):
        score += 1
        reasons.append("Frontline")
    if _damage(ally) == "AD" and _damage(cand) == "AP":
        score += 1
        reasons.append("Mixed Damage")
    if _damage(ally) == "AP" and _damage(cand) == "AD":
        score += 1
        reasons.append("Mixed Damage")
    return score, _dedup(reasons)


# -- ranking (tag floor + optional DB booster) -------------------------------
def rank_counters_for_enemy(enemy, candidates, *, session=None, role: str = "",
                            limit: int = 3) -> list[dict]:
    """Top ``limit`` pool ``candidates`` strongest into ``enemy``. ``session``
    (optional) enables the op.gg pairwise booster; without it the ranking is
    pure tag heuristic. Ties resolve to pool order (the player's own priority)."""
    edges = _counter_edges(session, enemy, candidates, role) if session is not None else {}
    ranked = []
    for cand in candidates:
        tag, reasons = score_candidate_into_enemy(cand, enemy)
        edge = edges.get(_name(cand))
        score = tag + (edge * DB_COUNTER_WEIGHT if edge is not None else 0.0)
        ranked.append(_entry(cand, score, reasons, edge))
    ranked.sort(key=lambda e: (e["score"], e["edge"] or 0.0), reverse=True)
    return ranked[:limit]


def rank_synergies_for_ally(ally, candidates, *, session=None, role: str = "",
                            limit: int = 3) -> list[dict]:
    """Top ``limit`` pool ``candidates`` that synergise best with ``ally``."""
    edges = _synergy_edges(session, ally, candidates, role) if session is not None else {}
    ranked = []
    for cand in candidates:
        tag, reasons = score_candidate_with_ally(cand, ally)
        syn = edges.get(_name(cand))
        score = tag + ((syn - 5.0) * DB_SYNERGY_WEIGHT if syn is not None else 0.0)
        ranked.append(_entry(cand, score, reasons, syn))
    ranked.sort(key=lambda e: (e["score"], e["edge"] or 0.0), reverse=True)
    return ranked[:limit]


def _entry(cand, score: float, reasons: list[str], edge) -> dict:
    """Compact, JSON-ready ranked entry the dashboard consumes."""
    return {
        "name": _name(cand),
        "slug": _slug(cand),
        "score": round(score, 1),
        "reasons": reasons[:2],
        "edge": round(edge, 1) if edge is not None else None,
    }


def _counter_edges(session, enemy, candidates, role: str) -> dict[str, float]:
    """``{candidate_name: advantage_score}`` for candidates vs this enemy, or {}
    when the DB lacks the rows. Best-effort: any failure degrades to tags."""
    try:
        names = [_name(c) for c in candidates]
        id_map = queries.champion_ids_by_name(session, names + [_name(enemy)])
        enemy_id = id_map.get(_name(enemy))
        if not enemy_id:
            return {}
        by_id = {id_map[n]: n for n in names if n in id_map}
        raw = queries.counters_against(session, enemy_id, role, list(by_id))
        return {by_id[cid]: adv for cid, adv in raw.items() if adv is not None}
    except Exception:
        log.debug("counter-edge lookup failed", exc_info=True)
        return {}


def _synergy_edges(session, ally, candidates, role: str) -> dict[str, float]:
    """``{candidate_name: synergy_score}`` for candidates with this ally, or {}."""
    try:
        names = [_name(c) for c in candidates]
        id_map = queries.champion_ids_by_name(session, names + [_name(ally)])
        ally_id = id_map.get(_name(ally))
        if not ally_id:
            return {}
        by_id = {id_map[n]: n for n in names if n in id_map}
        raw = queries.synergies_with(session, ally_id, role, list(by_id))
        return {by_id[cid]: syn for cid, syn in raw.items() if syn is not None}
    except Exception:
        log.debug("synergy-edge lookup failed", exc_info=True)
        return {}
