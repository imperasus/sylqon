"""Offline tests for the RAG rune-retrieval layer.

Covers:
- build_chunk_text composition
- build_rune_threat_query phrasing per threat signal
- build_rune_index over static.MINOR_RUNES with a deterministic fake embedder
- retrieve_counter_runes: shape, ranking, graceful empty/None/dim-mismatch
- _rune_doctrine_lines wiring (RAG on/off + fallback)

No LCU, Ollama, or network required.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon.rag import rune_index, rune_retrieve

# ---------------------------------------------------------------------------
# Deterministic offline fakes (keyword bag-of-words)
# ---------------------------------------------------------------------------

_VOCAB = [
    "damage", "mitigate", "reduce", "incoming", "burst",
    "heal", "health", "sustain", "durability", "bonus",
    "tenacity", "crowd", "control", "resistance",
    "magic", "shield", "mana",
]


class FakeEmbedder:
    model = "fake-embed"

    def available(self) -> bool:
        return True

    def embed(self, text: str):
        if not text:
            return None
        t = text.lower()
        return [float(t.count(w)) for w in _VOCAB]

    def embed_many(self, texts):
        return [self.embed(t) for t in texts]


class NullEmbedder(FakeEmbedder):
    def available(self) -> bool:
        return False

    def embed(self, text: str):
        return None


# Keyword-rich descriptions for the runes we assert on (by id).
_DESCRIPTIONS = {
    8473: {"short": "Reduce incoming damage from the next champion hits, mitigate burst.", "long": ""},   # Bone Plating
    8444: {"short": "Restore health after taking damage, heal and sustain in lane.", "long": ""},         # Second Wind
    8451: {"short": "Gain permanent bonus maximum health for durability.", "long": ""},                   # Overgrowth
    8242: {"short": "Gain tenacity and slow resistance against crowd control.", "long": ""},              # Unflinching
    8224: {"short": "Gain a magic damage shield when low on health, magic mitigation.", "long": ""},      # Nullifying Orb
    8226: {"short": "Restore mana on takedown and gain maximum mana.", "long": ""},                       # Manaflow Band
}


def _threat(**kw) -> dict:
    base = {
        "heavy_healing": False, "tanks": 0, "suppression": False,
        "heavy_cc_count": 0, "burst_ad": False, "burst_ap": False,
        "physical_threats": 0, "magic_threats": 0,
    }
    base.update(kw)
    return base


def _index() -> dict:
    idx = rune_index.build_rune_index(FakeEmbedder(), _DESCRIPTIONS)
    assert idx is not None
    return idx


# ---------------------------------------------------------------------------
# build_chunk_text
# ---------------------------------------------------------------------------

def test_chunk_text_includes_name_tree_desc():
    text = rune_index.build_chunk_text(
        "Second Wind", "Resolve", {"short": "Heal after taking damage", "long": "Long form"})
    assert "Second Wind" in text
    assert "Resolve rune" in text
    assert "Heal after taking damage" in text


def test_chunk_text_handles_missing_desc():
    text = rune_index.build_chunk_text("Triumph", "Precision", {})
    assert text == "Triumph (Precision rune)"


# ---------------------------------------------------------------------------
# build_rune_threat_query
# ---------------------------------------------------------------------------

def test_query_burst_mentions_durability():
    q = rune_retrieve.build_rune_threat_query(_threat(burst_ad=True))
    assert "durability" in q.lower()


def test_query_cc_mentions_tenacity():
    q = rune_retrieve.build_rune_threat_query(_threat(suppression=True))
    assert "tenacity" in q.lower()


def test_query_magic_mentions_magic_mitigation():
    q = rune_retrieve.build_rune_threat_query(_threat(magic_threats=3))
    assert "magic" in q.lower()


def test_query_empty_has_fallback():
    q = rune_retrieve.build_rune_threat_query(_threat())
    assert "no dominant" in q.lower()


# ---------------------------------------------------------------------------
# build_rune_index
# ---------------------------------------------------------------------------

def test_build_index_covers_all_minor_runes():
    from sylqon.data import static
    idx = _index()
    assert idx["model"] == "fake-embed"
    assert idx["dim"] == len(_VOCAB)
    assert len(idx["items"]) == len(static.MINOR_RUNES)
    entry = idx["items"][0]
    assert set(entry) >= {"id", "name", "tree", "description", "vector"}


def test_build_index_none_when_embeddings_fail():
    assert rune_index.build_rune_index(NullEmbedder(), _DESCRIPTIONS) is None


# ---------------------------------------------------------------------------
# retrieve_counter_runes
# ---------------------------------------------------------------------------

def test_retrieve_shape():
    res = rune_retrieve.retrieve_counter_runes(
        _threat(burst_ad=True), index=_index(), embedder=FakeEmbedder(), limit=3)
    assert res
    for r in res:
        assert set(r) >= {"id", "name", "tree", "description"}


def test_retrieve_cc_ranks_unflinching_first():
    res = rune_retrieve.retrieve_counter_runes(
        _threat(suppression=True, heavy_cc_count=3), index=_index(),
        embedder=FakeEmbedder(), limit=5)
    assert res[0]["name"] == "Unflinching"


def test_retrieve_magic_ranks_nullifying_orb_first():
    res = rune_retrieve.retrieve_counter_runes(
        _threat(magic_threats=3), index=_index(), embedder=FakeEmbedder(), limit=5)
    assert res[0]["name"] == "Nullifying Orb"


def test_retrieve_burst_surfaces_durability_runes():
    res = rune_retrieve.retrieve_counter_runes(
        _threat(burst_ap=True), index=_index(), embedder=FakeEmbedder(), limit=4)
    names = {r["name"] for r in res}
    assert {"Bone Plating", "Second Wind"} & names


def test_retrieve_honors_limit():
    res = rune_retrieve.retrieve_counter_runes(
        _threat(burst_ad=True), index=_index(), embedder=FakeEmbedder(), limit=2)
    assert len(res) == 2


def test_retrieve_empty_index_returns_empty():
    assert rune_retrieve.retrieve_counter_runes(
        _threat(burst_ad=True), index={"items": []}, embedder=FakeEmbedder()) == []


def test_retrieve_none_embedding_returns_empty():
    assert rune_retrieve.retrieve_counter_runes(
        _threat(burst_ad=True), index=_index(), embedder=NullEmbedder()) == []


def test_retrieve_dim_mismatch_returns_empty():
    bad = {"items": [{"id": 1, "name": "X", "tree": "Resolve", "description": "", "vector": [1.0, 2.0]}]}
    assert rune_retrieve.retrieve_counter_runes(
        _threat(burst_ad=True), index=bad, embedder=FakeEmbedder()) == []


# ---------------------------------------------------------------------------
# _rune_doctrine_lines wiring
# ---------------------------------------------------------------------------

def test_doctrine_lines_no_rag_when_disabled(monkeypatch):
    from sylqon import config
    from sylqon.ai import open_build_prompt as obp

    monkeypatch.setattr(config, "RAG_RUNES_MODE", False)
    lines = obp._rune_doctrine_lines(_threat(burst_ad=True))
    assert not any("Threat-matched flexible" in ln for ln in lines)


def test_doctrine_lines_appends_rag_when_enabled(monkeypatch):
    from sylqon import config
    from sylqon.ai import open_build_prompt as obp

    monkeypatch.setattr(config, "RAG_RUNES_MODE", True)
    monkeypatch.setattr(
        rune_retrieve, "retrieve_counter_runes",
        lambda *a, **k: [{"id": 8473, "name": "Bone Plating", "tree": "Resolve",
                          "description": "reduce burst"}],
    )
    lines = obp._rune_doctrine_lines(_threat(burst_ap=True))
    assert any("Bone Plating" in ln and "Threat-matched flexible" in ln for ln in lines)


def test_doctrine_lines_fallback_when_rag_raises(monkeypatch):
    from sylqon import config
    from sylqon.ai import open_build_prompt as obp

    monkeypatch.setattr(config, "RAG_RUNES_MODE", True)

    def boom(*a, **k):
        raise RuntimeError("embed down")

    monkeypatch.setattr(rune_retrieve, "retrieve_counter_runes", boom)
    lines = obp._rune_doctrine_lines(_threat(burst_ad=True))
    assert lines  # base directives survive
    assert not any("Threat-matched flexible" in ln for ln in lines)
