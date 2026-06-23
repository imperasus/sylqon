"""Builds and persists the rune embedding index used by ``rune_retrieve``.

Parallel to ``item_index`` but over the ~60 minor (non-keystone) runes the
project recognises in ``static.MINOR_RUNES``. The keystone is deliberately NOT
indexed: it stays champion/meta-anchored (like op.gg's core items), and RAG only
enriches the flexible secondary/defensive rune picks against the enemy threat.

Reuses ``item_index``'s generic atomic ``save_index`` / ``load_index`` (they take
an explicit path) so there is one IO implementation for both indexes.
"""
from __future__ import annotations

import logging
import re

import requests

from sylqon import config
from sylqon.data import static
from sylqon.data.catalog import DDRAGON_BASE
from sylqon.rag.embed import OllamaEmbedder
from sylqon.rag.item_index import load_index, save_index

log = logging.getLogger(__name__)

_DESC_MAX = 300


def _strip(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def fetch_rune_descriptions(patch: str) -> dict[int, dict]:
    """Map rune id -> {short, long} from the DDragon runesReforged.json for
    ``patch``. Returns ``{}`` on any failure (builder then falls back to names
    + tree only)."""
    try:
        trees = requests.get(
            f"{DDRAGON_BASE}/cdn/{patch}/data/en_US/runesReforged.json", timeout=20
        ).json()
    except (requests.RequestException, ValueError) as exc:
        log.warning("Rune description fetch failed for patch %s: %s", patch, exc)
        return {}
    out: dict[int, dict] = {}
    for tree in trees:
        for slot in tree.get("slots", []):
            for rune in slot.get("runes", []):
                rid = rune.get("id")
                if not rid:
                    continue
                out[rid] = {"short": _strip(rune.get("shortDesc", "")),
                            "long": _strip(rune.get("longDesc", ""))}
    return out


def build_chunk_text(name: str, tree: str, desc: dict) -> str:
    """Compose the embedded text for one rune. Pure/testable."""
    parts: list[str] = [f"{name} ({tree} rune)" if tree else name]
    if desc.get("short"):
        parts.append(desc["short"])
    if desc.get("long"):
        parts.append(desc["long"][:_DESC_MAX])
    return ". ".join(p for p in parts if p)


def build_rune_index(embedder: OllamaEmbedder,
                     descriptions: dict[int, dict] | None = None) -> dict | None:
    """Embed every recognised minor rune. Returns the index dict (no patch key —
    ``ensure_rune_index`` stamps it) or ``None`` if every embedding failed."""
    descriptions = descriptions or {}
    entries: list[dict] = []
    texts: list[str] = []
    for name, rid in static.MINOR_RUNES.items():
        tree = static.RUNE_STYLE_OF_MINOR.get(name, "")
        desc = descriptions.get(rid, {})
        entries.append({
            "id": rid,
            "name": name,
            "tree": tree,
            "description": desc.get("short") or desc.get("long", "")[:_DESC_MAX],
        })
        texts.append(build_chunk_text(name, tree, desc))

    vectors = embedder.embed_many(texts)
    indexed = [{**e, "vector": v} for e, v in zip(entries, vectors) if v is not None]
    if not indexed:
        log.warning("All rune embeddings failed; index not built")
        return None
    return {"model": embedder.model, "dim": len(indexed[0]["vector"]), "items": indexed}


def ensure_rune_index(catalog, embedder: OllamaEmbedder | None = None,
                      *, force: bool = False) -> dict | None:
    """Return a current rune index, rebuilding when the patch or model changed
    (or ``force``). Never raises; returns the existing (possibly stale) index
    when the embedder is unavailable."""
    embedder = embedder or OllamaEmbedder()
    path = config.RAG_RUNE_INDEX_PATH
    existing = load_index(path)
    if (existing and not force
            and existing.get("patch") == catalog.patch
            and existing.get("model", "").split(":")[0] == embedder.model.split(":")[0]):
        return existing

    if not embedder.available():
        log.info("Embedder unavailable; keeping existing rune index (%s)",
                 "present" if existing else "absent")
        return existing

    descriptions = fetch_rune_descriptions(catalog.patch)
    index = build_rune_index(embedder, descriptions)
    if index:
        index["patch"] = catalog.patch
        save_index(index, path)
        log.info("Built RAG rune index for patch %s (%d runes, dim %d)",
                 index["patch"], len(index["items"]), index["dim"])
        return index
    return existing


def main() -> None:
    """Manual rune index build: ``python -m sylqon.rag.rune_index``."""
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from sylqon.data.catalog import Catalog

    catalog = Catalog()
    catalog.refresh_if_stale()
    index = ensure_rune_index(catalog, force=True)
    if index:
        print(f"Built rune index: patch={index['patch']} "
              f"runes={len(index['items'])} dim={index['dim']}")
    else:
        print("Rune index build failed — is the embedding model installed in Ollama? "
              f"(SYLQON_RAG_EMBED_MODEL={config.RAG_EMBED_MODEL})")


if __name__ == "__main__":
    main()
