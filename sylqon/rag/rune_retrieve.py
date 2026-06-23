"""Semantic counter-rune retrieval — grounds the flexible/secondary rune picks
in real DDragon rune descriptions instead of the hand-coded ``rune_directives``.

The keystone is never retrieved here (it is not in the index): it stays
champion/meta-anchored. This only ranks which *flexible* runes best answer the
enemy threat, so the prompt can prefer them for the secondary/flex slots.

Graceful: returns ``[]`` (caller keeps the base ``rune_directives``) when the
index is missing or embedding fails.
"""
from __future__ import annotations

import logging

import numpy as np

from sylqon.rag.embed import OllamaEmbedder
from sylqon.rag.item_retrieve import _cosine_topk

log = logging.getLogger(__name__)


def build_rune_threat_query(threat: dict) -> str:
    """Turn the ``team_threat_summary()`` dict into a rune-flavoured counter
    query whose wording matches rune descriptions (durability vs burst,
    tenacity vs CC, mitigation vs sustained damage)."""
    lines: list[str] = []
    if threat.get("burst_ad") or threat.get("burst_ap"):
        lines.append("Need durability against burst damage: reduce incoming early "
                     "damage, restore health after taking damage, gain a shield, "
                     "grow bonus health.")
    if threat.get("suppression") or threat.get("heavy_cc_count", 0) >= 3:
        lines.append("Need tenacity and crowd control resistance to keep moving "
                     "and acting while crowd controlled.")
    if threat.get("physical_threats", 0) >= 4:
        lines.append("The enemy deals sustained physical attack damage: durability "
                     "runes that mitigate repeated hits and heal in lane.")
    if threat.get("magic_threats", 0) >= 3:
        lines.append("The enemy deals magic ability power damage: magic damage "
                     "mitigation and shielding runes.")
    if threat.get("heavy_healing"):
        lines.append("The enemy out-sustains trades: runes for sustained trading "
                     "and lane staying power.")
    if not lines:
        lines.append("No dominant threat: prefer tempo, scaling and utility runes "
                     "that maximise damage and power spikes.")
    return " ".join(lines)


def retrieve_counter_runes(threat: dict, *, limit: int = 6,
                           index: dict | None = None,
                           embedder: OllamaEmbedder | None = None) -> list[dict]:
    """Return up to ``limit`` flexible runes by semantic similarity to the threat
    profile, as ``[{id, name, tree, description}]``. ``[]`` on any failure."""
    if index is None:
        from sylqon import config
        from sylqon.rag.item_index import load_index
        index = load_index(config.RAG_RUNE_INDEX_PATH)
    items = (index or {}).get("items") or []
    if not items:
        return []

    embedder = embedder or OllamaEmbedder((index or {}).get("model"))
    qvec = embedder.embed(build_rune_threat_query(threat))
    if qvec is None:
        return []

    matrix = np.asarray([it["vector"] for it in items], dtype=np.float32)
    if matrix.ndim != 2 or matrix.shape[1] != len(qvec):
        log.warning("Query/index dim mismatch (%d vs %s); skipping RAG rune retrieval",
                    len(qvec), matrix.shape)
        return []

    ranked = _cosine_topk(qvec, matrix, k=limit)
    out: list[dict] = []
    for i, score in ranked:
        it = items[i]
        out.append({
            "id": it["id"],
            "name": it["name"],
            "tree": it.get("tree", ""),
            "description": it.get("description", ""),
            "score": round(score, 4),
        })
        if len(out) >= limit:
            break
    return out
