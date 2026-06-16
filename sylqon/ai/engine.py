"""Ollama evaluation engine.

Determinism is enforced at the API level: temperature 0, top_k 1, fixed
seed, tight num_predict budget and format="json" for strict raw JSON output.
Any failure returns None — the caller falls back to the deterministic
candidate build, so the AI can degrade but never block an injection.
"""
from __future__ import annotations

import json
import logging

import requests

from sylqon import config

log = logging.getLogger(__name__)


class OllamaEngine:
    def __init__(self) -> None:
        self.url = f"{config.OLLAMA_URL}/api/generate"
        self.model = config.OLLAMA_MODEL
        self._resolved = False

    def available(self) -> bool:
        try:
            resp = requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=3)
        except requests.RequestException:
            return False
        if resp.status_code != 200:
            return False
        if not self._resolved:
            self._resolve_model(resp)
        return True

    def _resolve_model(self, tags_resp) -> None:
        """Match the configured model against installed tags, so 'llama3.1'
        finds an installed 'llama3.1:8b'."""
        try:
            names = [m["name"] for m in tags_resp.json().get("models", [])]
        except (ValueError, KeyError, TypeError):
            return
        if self.model not in names:
            match = next((n for n in names if n.split(":")[0] == self.model.split(":")[0]), None)
            if match:
                log.info("Model '%s' not installed; using '%s'", self.model, match)
                self.model = match
        self._resolved = True

    def evaluate(self, prompt: str, options: dict | None = None) -> dict | None:
        """Run the prompt and parse the JSON object response. ``options`` overrides
        individual generation params (e.g. a larger ``num_predict`` for prompts
        that legitimately produce longer JSON, like multi-variant builds) — the
        default tight budget stays for the latency-sensitive injection path."""
        opts = dict(config.OLLAMA_OPTIONS)
        if options:
            opts.update(options)
        try:
            resp = requests.post(
                self.url,
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": opts,
                },
                timeout=config.OLLAMA_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            raw = resp.json().get("response", "")
        except requests.RequestException as exc:
            log.warning("Ollama request failed: %s", exc)
            return None
        except ValueError:
            log.warning("Ollama returned a non-JSON envelope")
            return None

        try:
            parsed = json.loads(raw)
        except ValueError:
            log.warning("Ollama response was not valid JSON: %.120s", raw)
            return None
        if not isinstance(parsed, dict):
            log.warning("Ollama JSON was not an object")
            return None
        return parsed
