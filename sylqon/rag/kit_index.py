"""Builds and persists the champion-kit embedding index used by ``kit_retrieve``.

One embedded chunk per ability (passive + Q/W/E/R) from DDragon
``championFull.json`` — the rich per-champion data the catalog does NOT store
(catalog only keeps name/tags/attack/magic). This is the knowledge base for
Pattern B (factual grounding): the lane-plan FACT SHEET references real ability
text instead of letting the 8B model hallucinate kits.

Building is a background/offline job (championFull.json is several MB and there
are ~850 abilities to embed), so it never runs on the latency-sensitive path.
"""
from __future__ import annotations

import logging
import re

import requests

from sylqon import config
from sylqon.data.catalog import DDRAGON_BASE
from sylqon.rag.embed import OllamaEmbedder
from sylqon.rag.item_index import load_index, save_index

log = logging.getLogger(__name__)

_DESC_MAX = 320
_SPELL_SLOTS = ("Q", "W", "E", "R")


def _strip(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def fetch_champion_kits(patch: str) -> dict:
    """Return the ``data`` map (slug -> champion) from championFull.json for
    ``patch``. ``{}`` on any failure."""
    try:
        # championFull.json is several MB; use a generous timeout.
        return requests.get(
            f"{DDRAGON_BASE}/cdn/{patch}/data/en_US/championFull.json", timeout=40
        ).json()["data"]
    except (requests.RequestException, KeyError, ValueError) as exc:
        log.warning("Champion kit fetch failed for patch %s: %s", patch, exc)
        return {}


def build_chunk_text(champion: str, slot: str, ability: dict) -> str:
    """Compose the embedded text for one ability. Pure/testable."""
    parts: list[str] = [f"{champion} {slot}: {ability.get('name', '')}".strip()]
    desc = _strip(ability.get("description", ""))
    if desc:
        parts.append(desc[:_DESC_MAX])
    meta: list[str] = []
    cd = ability.get("cooldownBurn")
    cost = ability.get("costBurn")
    rng = ability.get("rangeBurn")
    if cd and cd not in ("0", ""):
        meta.append(f"cooldown {cd}s")
    if cost and cost not in ("0", "", "No Cost"):
        meta.append(f"cost {cost}")
    if rng and rng not in ("0", "", "self"):
        meta.append(f"range {rng}")
    if meta:
        parts.append("(" + ", ".join(meta) + ")")
    return ". ".join(p for p in parts if p)


def _abilities(champ: dict) -> list[tuple[str, dict]]:
    """Ordered (slot, ability) pairs: Passive, then Q/W/E/R."""
    out: list[tuple[str, dict]] = []
    passive = champ.get("passive")
    if isinstance(passive, dict):
        out.append(("Passive", passive))
    for i, spell in enumerate(champ.get("spells", [])[:4]):
        if isinstance(spell, dict):
            out.append((_SPELL_SLOTS[i], spell))
    return out


def build_kit_index(embedder: OllamaEmbedder, kits: dict) -> dict | None:
    """Embed every ability of every champion in ``kits`` (championFull data map).
    Returns the index (no patch key — ``ensure_kit_index`` stamps it) or ``None``
    if every embedding failed / there is nothing to index."""
    entries: list[dict] = []
    texts: list[str] = []
    for slug, champ in kits.items():
        name = champ.get("name", slug)
        for slot, ability in _abilities(champ):
            ab_name = ability.get("name", "")
            desc = _strip(ability.get("description", ""))
            if not ab_name and not desc:
                continue
            entries.append({
                "champion": name,
                "slug": slug,
                "slot": slot,
                "ability": ab_name,
                "description": desc[:_DESC_MAX],
            })
            texts.append(build_chunk_text(name, slot, ability))

    if not entries:
        log.warning("No abilities to index")
        return None

    vectors = embedder.embed_many(texts)
    indexed = [{**e, "vector": v} for e, v in zip(entries, vectors) if v is not None]
    if not indexed:
        log.warning("All kit embeddings failed; index not built")
        return None
    return {"model": embedder.model, "dim": len(indexed[0]["vector"]), "items": indexed}


def ensure_kit_index(catalog, embedder: OllamaEmbedder | None = None,
                     *, force: bool = False) -> dict | None:
    """Return a current kit index, rebuilding on patch/model change (or
    ``force``). Never raises; returns the existing index when the embedder is
    unavailable."""
    embedder = embedder or OllamaEmbedder()
    path = config.RAG_KIT_INDEX_PATH
    existing = load_index(path)
    if (existing and not force
            and existing.get("patch") == catalog.patch
            and existing.get("model", "").split(":")[0] == embedder.model.split(":")[0]):
        return existing

    if not embedder.available():
        log.info("Embedder unavailable; keeping existing kit index (%s)",
                 "present" if existing else "absent")
        return existing

    kits = fetch_champion_kits(catalog.patch)
    index = build_kit_index(embedder, kits)
    if index:
        index["patch"] = catalog.patch
        save_index(index, path)
        log.info("Built RAG kit index for patch %s (%d abilities, dim %d)",
                 index["patch"], len(index["items"]), index["dim"])
        return index
    return existing


def main() -> None:
    """Manual kit index build: ``python -m sylqon.rag.kit_index``."""
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from sylqon.data.catalog import Catalog

    catalog = Catalog()
    catalog.refresh_if_stale()
    index = ensure_kit_index(catalog, force=True)
    if index:
        print(f"Built kit index: patch={index['patch']} "
              f"abilities={len(index['items'])} dim={index['dim']}")
    else:
        print("Kit index build failed — is the embedding model installed in Ollama? "
              f"(SYLQON_RAG_EMBED_MODEL={config.RAG_EMBED_MODEL})")


if __name__ == "__main__":
    main()
