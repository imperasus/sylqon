"""Ollama embeddings client for the RAG item-retrieval layer.

Mirrors ``ai/engine.py``'s contract: any failure (Ollama unreachable, model not
installed, malformed response) returns ``None`` — never raises — so the
retrieval layer can always fall back to the deterministic
``Catalog.items_for_threat`` path.

Embeddings are deterministic for a fixed model + input, so this preserves the
project-wide determinism rule (temperature 0 / seed 1337) for the build
pipeline: the same threat profile always retrieves the same items.
"""
from __future__ import annotations

import logging

import requests

from sylqon import config

log = logging.getLogger(__name__)


class OllamaEmbedder:
    def __init__(self, model: str | None = None) -> None:
        self.base = config.OLLAMA_URL
        self.model = model or config.RAG_EMBED_MODEL
        self._resolved = False

    def available(self) -> bool:
        try:
            resp = requests.get(f"{self.base}/api/tags", timeout=3)
        except requests.RequestException:
            return False
        if resp.status_code != 200:
            return False
        if not self._resolved:
            self._resolve_model(resp)
        return True

    def _resolve_model(self, tags_resp) -> None:
        """Match the configured model against installed tags, so
        'nomic-embed-text' finds an installed 'nomic-embed-text:latest'."""
        try:
            names = [m["name"] for m in tags_resp.json().get("models", [])]
        except (ValueError, KeyError, TypeError):
            return
        if self.model not in names:
            match = next(
                (n for n in names if n.split(":")[0] == self.model.split(":")[0]), None
            )
            if match:
                log.info("Embed model '%s' not installed; using '%s'", self.model, match)
                self.model = match
        self._resolved = True

    def embed(self, text: str) -> list[float] | None:
        """Embed a single string. Returns the vector or ``None`` on any failure."""
        if not text:
            return None
        try:
            resp = requests.post(
                f"{self.base}/api/embeddings",
                json={"model": self.model, "prompt": text},
                timeout=config.RAG_EMBED_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            vec = resp.json().get("embedding")
        except requests.RequestException as exc:
            log.warning("Ollama embed request failed: %s", exc)
            return None
        except ValueError:
            log.warning("Ollama embed returned a non-JSON envelope")
            return None
        if not isinstance(vec, list) or not vec:
            log.warning("Ollama embed response had no vector")
            return None
        try:
            return [float(x) for x in vec]
        except (TypeError, ValueError):
            log.warning("Ollama embed vector had non-numeric entries")
            return None

    def embed_many(self, texts: list[str]) -> list[list[float] | None]:
        """Embed a list of strings one-by-one (None for any that fail)."""
        return [self.embed(t) for t in texts]
