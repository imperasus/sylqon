"""Semantic counter-item retrieval — a smarter, patch-resilient drop-in for
``Catalog.items_for_threat``.

Given the enemy threat profile, it builds a natural-language counter query,
embeds it, and returns the most semantically similar completed items from the
prebuilt embedding index. The return shape is **identical** to
``items_for_threat`` (``list[{id, name, description, counter_tags}]``) so it
slots straight into ``ai.open_build_prompt`` without touching the prompt.

Why this is "smarter": ``items_for_threat`` can only ever suggest items a human
hand-tagged in ``static.ITEM_COUNTER_TAGS``, and that table drifts every patch.
Here the item's own Data Dragon description is the source of truth, so a
mechanically-correct counter surfaces even if nobody tagged it, and new/reworked
items are handled automatically.

Fully graceful: if the index is missing or embedding fails it returns ``[]`` and
the caller falls back to the deterministic ``items_for_threat`` path. The meta
soundness still comes from op.gg (its picks rank first in ``_merge_pools``);
this only enriches the *situational* suggestions.
"""
from __future__ import annotations

import logging

import numpy as np

from sylqon.data import static
from sylqon.rag.embed import OllamaEmbedder

log = logging.getLogger(__name__)


def build_threat_query(threat: dict, champion: str | None = None,
                       damage_type: str | None = None) -> str:
    """Turn the ``team_threat_summary()`` dict into a natural-language counter
    query whose wording semantically matches the relevant item descriptions
    (e.g. "Grievous Wounds and healing reduction" → Morellonomicon/Mortal
    Reminder, whose full descriptions name that mechanic)."""
    lines: list[str] = []
    if threat.get("heavy_healing"):
        lines.append("The enemy team has strong healing, lifesteal and health "
                     "regeneration; counter with Grievous Wounds and healing reduction.")
    tanks = threat.get("tanks", 0)
    if tanks >= 2:
        lines.append("The enemy has multiple tanks with high armor and health; "
                     "counter with armor penetration, percent armor penetration "
                     "and percent maximum health damage.")
    elif tanks == 1:
        lines.append("The enemy has a tank; armor penetration or percent maximum "
                     "health damage is valuable.")
    if threat.get("suppression") or threat.get("heavy_cc_count", 0) >= 3:
        lines.append("The enemy has heavy crowd control and suppression; counter "
                     "with crowd control removal, cleanse and tenacity.")
    if threat.get("burst_ad") or threat.get("burst_ap"):
        lines.append("The enemy has burst assassins; counter with survivability, "
                     "stasis invulnerability, a revive and shields.")
    if threat.get("physical_threats", 0) >= 4:
        lines.append("The enemy deals mostly physical attack damage; build armor.")
    if threat.get("magic_threats", 0) >= 3:
        lines.append("The enemy deals mostly magic ability power damage; build magic resist.")
    if not lines:
        lines.append("No dominant enemy threat; prefer the highest damage and "
                     "strongest power-spike items.")

    prefix = ""
    if champion:
        prefix = f"Counter items for {champion}"
        if damage_type:
            prefix += f" ({damage_type} damage)"
        prefix += ". "
    return prefix + " ".join(lines)


def _cosine_topk(query_vec: list[float], matrix: np.ndarray, k: int) -> list[tuple[int, float]]:
    """Top-k rows of ``matrix`` by cosine similarity to ``query_vec``.

    Stable sort so ties resolve to index order, keeping retrieval deterministic.
    """
    q = np.asarray(query_vec, dtype=np.float32)
    qn = float(np.linalg.norm(q))
    if qn == 0.0:
        return []
    q = q / qn
    norms = np.linalg.norm(matrix, axis=1)
    norms[norms == 0.0] = 1.0
    sims = (matrix @ q) / norms
    order = np.argsort(-sims, kind="stable")[:k]
    return [(int(i), float(sims[i])) for i in order]


def retrieve_counter_items(threat: dict, *, champion: str | None = None,
                           damage_type: str | None = None,
                           exclude_ids: set[int] | None = None,
                           limit: int = 12,
                           index: dict | None = None,
                           embedder: OllamaEmbedder | None = None) -> list[dict]:
    """Return up to ``limit`` counter items by semantic similarity to the threat
    profile, in the same shape as ``Catalog.items_for_threat``. Returns ``[]``
    (caller falls back) when the index is missing or embedding fails."""
    exclude_ids = set(exclude_ids or set())

    if index is None:
        from sylqon.rag import item_index
        index = item_index.load_index()
    items = (index or {}).get("items") or []
    if not items:
        return []

    embedder = embedder or OllamaEmbedder((index or {}).get("model"))
    query = build_threat_query(threat, champion, damage_type)
    qvec = embedder.embed(query)
    if qvec is None:
        return []

    matrix = np.asarray([it["vector"] for it in items], dtype=np.float32)
    if matrix.ndim != 2 or matrix.shape[1] != len(qvec):
        log.warning("Query/index dim mismatch (%d vs %s); skipping RAG retrieval",
                    len(qvec), matrix.shape)
        return []

    # Over-fetch so excluded (fixed) items don't shrink the result below limit.
    ranked = _cosine_topk(qvec, matrix, k=limit + len(exclude_ids) + 5)
    out: list[dict] = []
    for i, score in ranked:
        it = items[i]
        iid = it["id"]
        if iid in exclude_ids:
            continue
        out.append({
            "id": iid,
            "name": it["name"],
            "description": it.get("description", ""),
            # Reused only for the prompt's [tag] label when present; retrieval no
            # longer DEPENDS on this table.
            "counter_tags": list(static.ITEM_COUNTER_TAGS.get(iid, ())),
            "score": round(score, 4),
        })
        if len(out) >= limit:
            break
    return out
