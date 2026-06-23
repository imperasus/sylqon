"""Offline tests for the RAG item-retrieval layer.

Covers:
- build_chunk_text composition
- build_threat_query phrasing per threat signal
- build_index over a stub catalog with a deterministic fake embedder
- retrieve_counter_items: shape parity with items_for_threat, ranking,
  exclude_ids, and graceful empty/None paths
- _counter_items wiring: RAG on/off + fallback

No LCU, Ollama, or network required — a keyword bag-of-words fake embedder
stands in for the real model so cosine ranking is meaningful and deterministic.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon.rag import item_index, item_retrieve


# ---------------------------------------------------------------------------
# Deterministic offline fakes
# ---------------------------------------------------------------------------

# A tiny vocabulary; embed() returns the keyword counts, so cosine similarity
# rewards shared mechanic words (the same signal the real model captures).
_VOCAB = [
    "heal", "healing", "grievous", "wounds", "lifesteal",
    "armor", "penetration", "tank", "health",
    "magic", "resist", "ability",
    "crowd", "control", "cleanse", "tenacity",
    "burst", "surviv", "invulnerable", "revive", "shield",
    "damage",
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
    """Simulates a down/garbage embedding model."""

    def available(self) -> bool:
        return False

    def embed(self, text: str):
        return None


class StubCatalog:
    """Minimal Catalog surface used by build_index."""

    patch = "16.12.1"

    def __init__(self, items: dict[int, dict]):
        self._items = items

    def completed_items(self) -> dict[int, dict]:
        return self._items


def _catalog() -> StubCatalog:
    return StubCatalog({
        3033: {"id": 3033, "name": "Mortal Reminder",
               "plaintext": "Overcomes enemies with high Health recovery and Armor",
               "tags": ["Damage", "ArmorPenetration"]},
        3036: {"id": 3036, "name": "Lord Dominik's Regards",
               "plaintext": "Overcomes enemies with high health and armor",
               "tags": ["Damage", "ArmorPenetration"]},
        3156: {"id": 3156, "name": "Maw of Malmortius",
               "plaintext": "Grants a shield and magic resist",
               "tags": ["Damage", "SpellBlock"]},
        3026: {"id": 3026, "name": "Guardian Angel",
               "plaintext": "Periodically revives champion upon death",
               "tags": ["Damage", "Armor"]},
        3139: {"id": 3139, "name": "Mercurial Scimitar",
               "plaintext": "Activate to remove all crowd control debuffs",
               "tags": ["Damage", "SpellBlock", "Tenacity"]},
    })


# Full descriptions that name the mechanic the short plaintext omits.
_DESCRIPTIONS = {
    "Mortal Reminder": "Dealing physical damage inflicts Grievous Wounds reducing healing. "
                       "Grants armor penetration.",
    "Lord Dominik's Regards": "Deals bonus damage based on the target's maximum health. "
                              "Grants armor penetration against high-health tanks.",
    "Maw of Malmortius": "Grants magic resist and a lifeline shield against magic burst damage.",
    "Guardian Angel": "Upon taking lethal damage, revives your champion. Survive burst.",
    "Mercurial Scimitar": "Activate to remove all crowd control debuffs and gain move speed. "
                          "Cleanse and tenacity.",
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
    idx = item_index.build_index(_catalog(), FakeEmbedder(), _DESCRIPTIONS)
    assert idx is not None
    return idx


# ---------------------------------------------------------------------------
# build_chunk_text
# ---------------------------------------------------------------------------

def test_chunk_text_includes_name_plaintext_desc_tags():
    text = item_index.build_chunk_text(
        "Morellonomicon",
        {"plaintext": "Increases magic damage",
         "description": "Inflicts Grievous Wounds on enemies.",
         "tags": ["SpellDamage", "Health"]},
    )
    assert "Morellonomicon" in text
    assert "Increases magic damage" in text
    assert "Grievous Wounds" in text
    assert "Categories: SpellDamage, Health" in text


def test_chunk_text_handles_missing_fields():
    text = item_index.build_chunk_text("Thornmail", {"plaintext": "", "tags": ["Armor"]})
    assert text.startswith("Thornmail")
    assert "Armor" in text


def test_chunk_text_caps_long_description():
    long_desc = "x" * 1000
    text = item_index.build_chunk_text("Item", {"description": long_desc})
    assert len(text) < 600  # name + capped desc


# ---------------------------------------------------------------------------
# build_threat_query
# ---------------------------------------------------------------------------

def test_threat_query_healing_mentions_grievous():
    q = item_retrieve.build_threat_query(_threat(heavy_healing=True))
    assert "Grievous Wounds" in q


def test_threat_query_tanks_mention_penetration():
    q = item_retrieve.build_threat_query(_threat(tanks=2))
    assert "armor penetration" in q.lower()


def test_threat_query_cc_mentions_cleanse():
    q = item_retrieve.build_threat_query(_threat(suppression=True))
    assert "cleanse" in q.lower()


def test_threat_query_empty_threat_has_fallback():
    q = item_retrieve.build_threat_query(_threat())
    assert "no dominant" in q.lower()


def test_threat_query_includes_champion_prefix():
    q = item_retrieve.build_threat_query(_threat(tanks=1), champion="Caitlyn")
    assert q.startswith("Counter items for Caitlyn")


# ---------------------------------------------------------------------------
# build_index
# ---------------------------------------------------------------------------

def test_build_index_shape():
    idx = _index()
    assert idx["patch"] == "16.12.1"
    assert idx["model"] == "fake-embed"
    assert idx["dim"] == len(_VOCAB)
    assert len(idx["items"]) == 5
    entry = idx["items"][0]
    assert set(entry) >= {"id", "name", "description", "tags", "vector"}


def test_build_index_none_when_all_embeddings_fail():
    assert item_index.build_index(_catalog(), NullEmbedder(), _DESCRIPTIONS) is None


def test_build_index_none_on_empty_catalog():
    assert item_index.build_index(StubCatalog({}), FakeEmbedder()) is None


# ---------------------------------------------------------------------------
# retrieve_counter_items
# ---------------------------------------------------------------------------

def test_retrieve_shape_matches_items_for_threat():
    res = item_retrieve.retrieve_counter_items(
        _threat(heavy_healing=True), index=_index(), embedder=FakeEmbedder(), limit=3)
    assert res
    for item in res:
        assert set(item) >= {"id", "name", "description", "counter_tags"}
        assert isinstance(item["id"], int)
        assert isinstance(item["counter_tags"], list)


def test_retrieve_healing_ranks_grievous_item_first():
    res = item_retrieve.retrieve_counter_items(
        _threat(heavy_healing=True), index=_index(), embedder=FakeEmbedder(), limit=5)
    assert res[0]["name"] == "Mortal Reminder"  # only item naming Grievous Wounds


def test_retrieve_cc_ranks_cleanse_item_first():
    res = item_retrieve.retrieve_counter_items(
        _threat(suppression=True), index=_index(), embedder=FakeEmbedder(), limit=5)
    assert res[0]["name"] == "Mercurial Scimitar"


def test_retrieve_burst_ranks_revive_or_shield_first():
    res = item_retrieve.retrieve_counter_items(
        _threat(burst_ap=True), index=_index(), embedder=FakeEmbedder(), limit=5)
    assert res[0]["name"] in {"Guardian Angel", "Maw of Malmortius"}


def test_retrieve_respects_exclude_ids():
    res = item_retrieve.retrieve_counter_items(
        _threat(heavy_healing=True), index=_index(), embedder=FakeEmbedder(),
        exclude_ids={3033}, limit=5)
    assert all(item["id"] != 3033 for item in res)


def test_retrieve_honors_limit():
    res = item_retrieve.retrieve_counter_items(
        _threat(tanks=2), index=_index(), embedder=FakeEmbedder(), limit=2)
    assert len(res) == 2


def test_retrieve_empty_index_returns_empty():
    assert item_retrieve.retrieve_counter_items(
        _threat(tanks=2), index={"items": []}, embedder=FakeEmbedder()) == []


def test_retrieve_none_embedding_returns_empty():
    assert item_retrieve.retrieve_counter_items(
        _threat(tanks=2), index=_index(), embedder=NullEmbedder()) == []


def test_retrieve_dim_mismatch_returns_empty():
    bad_index = {"items": [{"id": 1, "name": "X", "description": "", "vector": [1.0, 2.0]}]}
    res = item_retrieve.retrieve_counter_items(
        _threat(tanks=2), index=bad_index, embedder=FakeEmbedder())
    assert res == []


# ---------------------------------------------------------------------------
# _counter_items wiring (open_build_prompt)
# ---------------------------------------------------------------------------

def test_counter_items_falls_back_when_rag_disabled(monkeypatch):
    from sylqon import config
    from sylqon.ai import open_build_prompt as obp

    monkeypatch.setattr(config, "RAG_ITEMS_MODE", False)

    class FakeCat:
        def items_for_threat(self, tags, exclude_ids, limit):
            return [{"id": 9999, "name": "FallbackItem",
                     "description": "from items_for_threat", "counter_tags": []}]

    class FakeCtx:
        my_champion = "Caitlyn"

    res = obp._counter_items(FakeCtx(), {}, FakeCat(), _threat(tanks=2), set(), 12)
    assert res[0]["name"] == "FallbackItem"


def test_counter_items_uses_rag_when_enabled(monkeypatch):
    from sylqon import config
    from sylqon.ai import open_build_prompt as obp

    monkeypatch.setattr(config, "RAG_ITEMS_MODE", True)
    monkeypatch.setattr(
        item_retrieve, "retrieve_counter_items",
        lambda *a, **k: [{"id": 3033, "name": "Mortal Reminder",
                          "description": "rag", "counter_tags": ["anti_heal"]}],
    )

    class FakeCat:
        def items_for_threat(self, tags, exclude_ids, limit):
            raise AssertionError("should not fall back when RAG returns items")

    class FakeCtx:
        my_champion = "Caitlyn"

    res = obp._counter_items(FakeCtx(), {}, FakeCat(), _threat(heavy_healing=True), set(), 12)
    assert res[0]["name"] == "Mortal Reminder"


def test_counter_items_falls_back_when_rag_empty(monkeypatch):
    from sylqon import config
    from sylqon.ai import open_build_prompt as obp

    monkeypatch.setattr(config, "RAG_ITEMS_MODE", True)
    monkeypatch.setattr(item_retrieve, "retrieve_counter_items", lambda *a, **k: [])

    class FakeCat:
        def items_for_threat(self, tags, exclude_ids, limit):
            return [{"id": 1, "name": "Fallback", "description": "", "counter_tags": []}]

    class FakeCtx:
        my_champion = "Caitlyn"

    res = obp._counter_items(FakeCtx(), {}, FakeCat(), _threat(heavy_healing=True), set(), 12)
    assert res[0]["name"] == "Fallback"
