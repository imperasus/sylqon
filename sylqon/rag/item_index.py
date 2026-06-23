"""Builds and persists the item embedding index used by ``item_retrieve``.

The index is a pure derivative of the Data Dragon catalog (one embedded chunk
per completed, situational-relevant item), so it shares the catalog's patch
lifecycle and lives next to ``ddragon_catalog.json`` in the writable cache dir.

Building is a background/offline job (it embeds ~100 short texts and may fetch
full item descriptions from the DDragon CDN) — it must never run on the
latency-sensitive injection path. The *read* path (``item_retrieve``) only ever
loads the prebuilt index, so it stays fast and network-free.

Chunk text quality matters: the catalog's short ``plaintext`` often omits the
mechanic we care about (e.g. Morellonomicon's plaintext is "Increases magic
damage" with no hint of Grievous Wounds), so the builder enriches each chunk
with the full HTML-stripped item description when available.
"""
from __future__ import annotations

import json
import logging
import re

import requests

from sylqon import config
from sylqon.data.catalog import DDRAGON_BASE
from sylqon.rag.embed import OllamaEmbedder

log = logging.getLogger(__name__)

_DESC_MAX = 400  # cap rich descriptions so chunks stay focused


def build_chunk_text(name: str, data: dict) -> str:
    """Compose the text embedded for one item from its catalog/description data.

    Pure and deterministic so it is unit-testable without a catalog or network.
    """
    parts: list[str] = [name]
    plain = (data.get("plaintext") or "").strip()
    if plain:
        parts.append(plain)
    desc = (data.get("description") or "").strip()
    if desc:
        parts.append(desc[:_DESC_MAX])
    tags = data.get("tags") or []
    if tags:
        parts.append("Categories: " + ", ".join(tags))
    return ". ".join(p for p in parts if p)


def fetch_item_descriptions(patch: str) -> dict[str, str]:
    """Fetch the full HTML-stripped item description per item name from the
    DDragon CDN for ``patch``. Returns ``{}`` on any failure — the builder then
    falls back to catalog plaintext + tags only."""
    try:
        items = requests.get(
            f"{DDRAGON_BASE}/cdn/{patch}/data/en_US/item.json", timeout=20
        ).json()["data"]
    except (requests.RequestException, KeyError, ValueError) as exc:
        log.warning("Item description fetch failed for patch %s: %s", patch, exc)
        return {}
    out: dict[str, str] = {}
    for it in items.values():
        name = (it.get("name") or "").strip()
        raw = it.get("description", "") or ""
        text = re.sub(r"<[^>]+>", " ", raw)
        text = re.sub(r"\s+", " ", text).strip()
        if name and text:
            out[name] = text
    return out


def build_index(catalog, embedder: OllamaEmbedder,
                descriptions: dict[str, str] | None = None) -> dict | None:
    """Embed every completed, situational-relevant catalog item.

    Returns the index dict (or ``None`` if the catalog is empty or every
    embedding failed). Items whose embedding fails are skipped, not fatal.
    """
    items = catalog.completed_items()  # {int id: {name, id, plaintext, tags, ...}}
    if not items:
        log.warning("Catalog has no completed items; cannot build index")
        return None
    descriptions = descriptions or {}

    entries: list[dict] = []
    texts: list[str] = []
    for iid, data in items.items():
        name = data["name"]
        merged = {**data, "description": descriptions.get(name, "")}
        text = build_chunk_text(name, merged)
        entries.append({
            "id": iid,
            "name": name,
            # what the retriever surfaces to the prompt — prefer the rich
            # description, fall back to the short plaintext.
            "description": merged["description"] or data.get("plaintext", ""),
            "tags": list(data.get("tags", [])),
        })
        texts.append(text)

    vectors = embedder.embed_many(texts)
    indexed: list[dict] = []
    for entry, vec in zip(entries, vectors):
        if vec is None:
            log.debug("Skipping %s — embedding failed", entry["name"])
            continue
        indexed.append({**entry, "vector": vec})

    if not indexed:
        log.warning("All item embeddings failed; index not built")
        return None

    return {
        "patch": catalog.patch,
        "model": embedder.model,
        "dim": len(indexed[0]["vector"]),
        "items": indexed,
    }


def save_index(index: dict, path=None) -> None:
    path = path or config.RAG_ITEM_INDEX_PATH
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(index), encoding="utf-8")
    tmp.replace(path)


def load_index(path=None) -> dict | None:
    path = path or config.RAG_ITEM_INDEX_PATH
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _model_matches(saved_model: str, want_model: str) -> bool:
    return saved_model.split(":")[0] == want_model.split(":")[0]


def ensure_index(catalog, embedder: OllamaEmbedder | None = None,
                 *, force: bool = False) -> dict | None:
    """Return a current index, rebuilding it when the patch or embedding model
    changed (or ``force``). Never raises; if the embedder is unavailable it
    returns whatever index already exists on disk (possibly stale, possibly
    ``None``) so callers degrade rather than break."""
    embedder = embedder or OllamaEmbedder()
    existing = load_index()
    if (existing and not force
            and existing.get("patch") == catalog.patch
            and _model_matches(existing.get("model", ""), embedder.model)):
        return existing

    if not embedder.available():
        log.info("Embedder unavailable; keeping existing item index (%s)",
                 "present" if existing else "absent")
        return existing

    descriptions = fetch_item_descriptions(catalog.patch)
    index = build_index(catalog, embedder, descriptions)
    if index:
        save_index(index)
        log.info("Built RAG item index for patch %s (%d items, dim %d)",
                 index["patch"], len(index["items"]), index["dim"])
        return index
    return existing


def main() -> None:
    """Manual index build: ``python -m sylqon.rag.item_index``."""
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from sylqon.data.catalog import Catalog

    catalog = Catalog()
    catalog.refresh_if_stale()
    index = ensure_index(catalog, force=True)
    if index:
        print(f"Built index: patch={index['patch']} "
              f"items={len(index['items'])} dim={index['dim']}")
    else:
        print("Index build failed — is the embedding model installed in Ollama? "
              f"(SYLQON_RAG_EMBED_MODEL={config.RAG_EMBED_MODEL})")


if __name__ == "__main__":
    main()
