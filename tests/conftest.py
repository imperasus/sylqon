"""Shared pytest fixtures for the offline suite.

The RAG feature flags are read from environment variables at import time
(SYLQON_RAG_ITEMS / RUNES / KIT / FUSION). A developer who has them enabled to
run the desktop app would otherwise make the offline suite route through the
live embedding index + Ollama — violating the "tests run fully offline" rule.

This autouse fixture pins every RAG flag OFF by default so the suite is hermetic
regardless of the local environment. Tests that exercise a RAG path opt back in
explicitly (``monkeypatch.setattr(config, "RAG_*_MODE", True)``), which overrides
this within that test.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _hermetic_rag_flags(monkeypatch):
    from sylqon import config
    for flag in ("RAG_ITEMS_MODE", "RAG_RUNES_MODE", "RAG_KIT_MODE", "RAG_FUSION_MODE"):
        monkeypatch.setattr(config, flag, False, raising=False)
