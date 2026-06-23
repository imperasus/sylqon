"""Champion-kit fact retrieval for lane-plan grounding (Pattern B).

Two retrieval modes over the kit index:
  - **keyed**: every ability of the focus champions (your champ + lane opponent),
    returned in Passive/Q/W/E/R order — a deterministic store lookup.
  - **semantic**: the top-K matchup-relevant abilities across the rest of the
    enemy team (their hard CC, all-in, dashes), ranked by embedding similarity to
    a matchup query — keeps the FACT SHEET focused and within token budget.

Graceful: returns ``[]`` / ``""`` when the index is missing or embedding fails,
so the lane plan simply runs ungrounded (its existing behavior).
"""
from __future__ import annotations

import logging

import numpy as np

from sylqon.rag.embed import OllamaEmbedder
from sylqon.rag.item_retrieve import _cosine_topk

log = logging.getLogger(__name__)

_SLOT_ORDER = {"Passive": 0, "Q": 1, "W": 2, "E": 3, "R": 4}
_FACT_KEYS = ("champion", "slot", "ability", "description")


def build_matchup_query(my_champion: str, enemies: list[str] | None) -> str:
    """Query that pulls the decision-relevant enemy abilities for laning/fights."""
    enemy_str = ", ".join(enemies) if enemies else "the enemy team"
    return (f"As {my_champion}, the key enemy abilities to respect against {enemy_str}: "
            f"hard crowd control such as stuns, roots, knockups and suppression; "
            f"all-in burst combos; gap-closers and dashes; poke and harass; "
            f"escapes, shields and self-peel.")


def retrieve_kit_facts(*, champions: list[str] | None = None,
                       query: str | None = None,
                       pool_champions: list[str] | None = None,
                       limit: int = 6,
                       index: dict | None = None,
                       embedder: OllamaEmbedder | None = None) -> list[dict]:
    """Keyed full kits for ``champions`` + up to ``limit`` semantically-retrieved
    abilities from ``pool_champions``. Returns ``[{champion, slot, ability,
    description}]`` (semantic entries also carry ``score``). ``[]`` on failure."""
    if index is None:
        from sylqon import config
        from sylqon.rag.item_index import load_index
        index = load_index(config.RAG_KIT_INDEX_PATH)
    items = (index or {}).get("items") or []
    if not items:
        return []

    facts: list[dict] = []
    seen: set[tuple[str, str]] = set()

    # -- keyed: full kit for each focus champion, in ability order --------------
    if champions:
        wanted = {c.lower() for c in champions}
        focus = [
            it for it in items
            if it["champion"].lower() in wanted or it.get("slug", "").lower() in wanted
        ]
        focus.sort(key=lambda x: (x["champion"], _SLOT_ORDER.get(x["slot"], 9)))
        for it in focus:
            key = (it["champion"], it["slot"])
            if key in seen:
                continue
            seen.add(key)
            facts.append({k: it[k] for k in _FACT_KEYS})

    # -- semantic: top-K matchup-relevant abilities from the enemy pool ---------
    if query and pool_champions:
        embedder = embedder or OllamaEmbedder((index or {}).get("model"))
        qvec = embedder.embed(query)
        if qvec is not None:
            pool = {c.lower() for c in pool_champions}
            cand = [it for it in items if it["champion"].lower() in pool]
            if cand:
                matrix = np.asarray([it["vector"] for it in cand], dtype=np.float32)
                if matrix.ndim == 2 and matrix.shape[1] == len(qvec):
                    added = 0
                    for i, score in _cosine_topk(qvec, matrix, k=limit + len(seen) + 5):
                        it = cand[i]
                        key = (it["champion"], it["slot"])
                        if key in seen:
                            continue
                        seen.add(key)
                        facts.append({**{k: it[k] for k in _FACT_KEYS},
                                      "score": round(score, 4)})
                        added += 1
                        if added >= limit:
                            break
                else:
                    log.warning("Kit query/index dim mismatch (%d vs %s); semantic "
                                "retrieval skipped", len(qvec), matrix.shape)
    return facts


def format_kit_facts(facts: list[dict]) -> str:
    """Render retrieved facts into a prompt FACT SHEET block, or ``""`` if empty."""
    lines = [
        f"- {f['champion']} {f['slot']} ({f['ability']}): {f['description']}"
        for f in facts if f.get("description")
    ]
    if not lines:
        return ""
    return ("CHAMPION ABILITY FACTS (real abilities for this matchup — reference "
            "these exact mechanics; do not invent cooldowns or effects):\n"
            + "\n".join(lines))
