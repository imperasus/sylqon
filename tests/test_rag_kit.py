"""Offline tests for the champion-kit grounding layer (Pattern B).

Covers:
- build_chunk_text composition (incl. cooldown/cost/range meta)
- build_kit_index over fake championFull data (passive + spells, ordering)
- retrieve_kit_facts: keyed full-kit lookup, semantic top-K, dedup overlap
- build_matchup_query phrasing
- format_kit_facts output
- _kit_fact_sheet wiring (RAG on/off + fallback)

No LCU, Ollama, or network required.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon.rag import kit_index, kit_retrieve


# ---------------------------------------------------------------------------
# Deterministic offline fakes
# ---------------------------------------------------------------------------

_VOCAB = [
    "stun", "root", "knockup", "suppression", "crowd", "control",
    "dash", "gap", "burst", "poke", "harass", "range",
    "shield", "durability", "slow", "escape", "damage",
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


def _kits() -> dict:
    return {
        "Caitlyn": {"name": "Caitlyn",
            "passive": {"name": "Headshot", "description": "Periodic bonus range auto attack poke."},
            "spells": [
                {"name": "Piltover Peacemaker", "description": "Long range line poke harass.",
                 "cooldownBurn": "10", "costBurn": "50", "rangeBurn": "1250"},
                {"name": "Yordle Snap Trap", "description": "Place a trap that roots enemies crowd control.",
                 "cooldownBurn": "0", "costBurn": "50", "rangeBurn": "800"},
                {"name": "90 Caliber Net", "description": "Dash backward escape and slow the target.",
                 "cooldownBurn": "16", "costBurn": "75", "rangeBurn": "750"},
                {"name": "Ace in the Hole", "description": "Long range execute burst damage.",
                 "cooldownBurn": "90", "costBurn": "100", "rangeBurn": "2000"},
            ]},
        "Leona": {"name": "Leona",
            "passive": {"name": "Sunlight", "description": "Allies deal bonus damage to marked targets."},
            "spells": [
                {"name": "Shield of Daybreak", "description": "Stun the target crowd control with a melee strike.",
                 "cooldownBurn": "6", "costBurn": "45", "rangeBurn": "125"},
                {"name": "Eclipse", "description": "Gain armor and magic resist shield durability.",
                 "cooldownBurn": "14", "costBurn": "60", "rangeBurn": "self"},
                {"name": "Zenith Blade", "description": "Dash gap-closer that roots and pulls to the target.",
                 "cooldownBurn": "10", "costBurn": "60", "rangeBurn": "875"},
                {"name": "Solar Flare", "description": "Area stun knockup and slow crowd control engage.",
                 "cooldownBurn": "90", "costBurn": "100", "rangeBurn": "1200"},
            ]},
        "Zed": {"name": "Zed",
            "passive": {"name": "Contempt for the Weak", "description": "Bonus damage to low health targets."},
            "spells": [
                {"name": "Razor Shuriken", "description": "Throw shurikens for poke and burst damage.",
                 "cooldownBurn": "6", "costBurn": "75", "rangeBurn": "900"},
                {"name": "Living Shadow", "description": "Dash via shadow gap-closer reposition.",
                 "cooldownBurn": "22", "costBurn": "40", "rangeBurn": "700"},
                {"name": "Shadow Slash", "description": "Slow nearby enemies with a spin.",
                 "cooldownBurn": "4", "costBurn": "50", "rangeBurn": "290"},
                {"name": "Death Mark", "description": "Dash to target and mark for delayed burst all-in.",
                 "cooldownBurn": "120", "costBurn": "0", "rangeBurn": "625"},
            ]},
    }


def _index() -> dict:
    idx = kit_index.build_kit_index(FakeEmbedder(), _kits())
    assert idx is not None
    return idx


# ---------------------------------------------------------------------------
# build_chunk_text
# ---------------------------------------------------------------------------

def test_chunk_text_includes_slot_name_desc_and_meta():
    text = kit_index.build_chunk_text(
        "Leona", "Q",
        {"name": "Shield of Daybreak", "description": "Stun the target.",
         "cooldownBurn": "6", "costBurn": "45", "rangeBurn": "125"})
    assert "Leona Q: Shield of Daybreak" in text
    assert "Stun the target" in text
    assert "cooldown 6s" in text and "range 125" in text


def test_chunk_text_omits_zero_meta():
    text = kit_index.build_chunk_text(
        "X", "W", {"name": "Free", "description": "d", "costBurn": "0", "rangeBurn": "self"})
    assert "cost" not in text and "range" not in text


# ---------------------------------------------------------------------------
# build_kit_index
# ---------------------------------------------------------------------------

def test_build_index_shape_and_count():
    idx = _index()
    assert idx["model"] == "fake-embed"
    assert idx["dim"] == len(_VOCAB)
    # 3 champions × (1 passive + 4 spells) = 15 abilities
    assert len(idx["items"]) == 15
    entry = idx["items"][0]
    assert set(entry) >= {"champion", "slug", "slot", "ability", "description", "vector"}


def test_build_index_handles_missing_passive_and_short_spells():
    kits = {"NoPassive": {"name": "NoPassive", "spells": [
        {"name": "OnlyQ", "description": "does a thing"}]}}
    idx = kit_index.build_kit_index(FakeEmbedder(), kits)
    slots = [it["slot"] for it in idx["items"]]
    assert slots == ["Q"]  # no passive entry, single spell


def test_build_index_none_when_embeddings_fail():
    assert kit_index.build_kit_index(NullEmbedder(), _kits()) is None


# ---------------------------------------------------------------------------
# retrieve_kit_facts
# ---------------------------------------------------------------------------

def test_keyed_returns_full_kit_in_slot_order():
    facts = kit_retrieve.retrieve_kit_facts(champions=["Caitlyn"], index=_index())
    assert [f["slot"] for f in facts] == ["Passive", "Q", "W", "E", "R"]
    assert all(f["champion"] == "Caitlyn" for f in facts)


def test_keyed_matches_by_slug_too():
    facts = kit_retrieve.retrieve_kit_facts(champions=["zed"], index=_index())
    assert facts and all(f["champion"] == "Zed" for f in facts)


def test_semantic_pulls_relevant_enemy_abilities():
    facts = kit_retrieve.retrieve_kit_facts(
        query=kit_retrieve.build_matchup_query("Caitlyn", ["Leona", "Zed"]),
        pool_champions=["Leona", "Zed"], limit=4,
        index=_index(), embedder=FakeEmbedder())
    assert 1 <= len(facts) <= 4
    # a CC/engage or dash/burst ability should surface
    abilities = {f["ability"] for f in facts}
    assert abilities & {"Shield of Daybreak", "Solar Flare", "Zenith Blade",
                        "Death Mark", "Living Shadow"}


def test_keyed_and_semantic_do_not_duplicate():
    facts = kit_retrieve.retrieve_kit_facts(
        champions=["Caitlyn", "Leona"],  # Leona keyed (full kit)
        query=kit_retrieve.build_matchup_query("Caitlyn", ["Leona", "Zed"]),
        pool_champions=["Leona", "Zed"], limit=5,
        index=_index(), embedder=FakeEmbedder())
    keys = [(f["champion"], f["slot"]) for f in facts]
    assert len(keys) == len(set(keys))  # no (champion, slot) duplicated


def test_retrieve_empty_index_returns_empty():
    assert kit_retrieve.retrieve_kit_facts(champions=["Caitlyn"], index={"items": []}) == []


def test_semantic_none_embedding_returns_keyed_only():
    facts = kit_retrieve.retrieve_kit_facts(
        champions=["Caitlyn"], query="q", pool_champions=["Zed"],
        index=_index(), embedder=NullEmbedder())
    assert facts and all(f["champion"] == "Caitlyn" for f in facts)


# ---------------------------------------------------------------------------
# format + query
# ---------------------------------------------------------------------------

def test_format_kit_facts():
    sheet = kit_retrieve.format_kit_facts([
        {"champion": "Leona", "slot": "Q", "ability": "Shield of Daybreak", "description": "Stun"}])
    assert "CHAMPION ABILITY FACTS" in sheet
    assert "Leona Q (Shield of Daybreak): Stun" in sheet


def test_format_empty():
    assert kit_retrieve.format_kit_facts([]) == ""


def test_matchup_query_mentions_cc_and_dashes():
    q = kit_retrieve.build_matchup_query("Caitlyn", ["Leona"])
    assert "crowd control" in q.lower()
    assert "dash" in q.lower()


# ---------------------------------------------------------------------------
# _kit_fact_sheet wiring (lane_plan)
# ---------------------------------------------------------------------------

class _Enemy:
    def __init__(self, name):
        self.name = name


class _Ctx:
    my_champion = "Caitlyn"
    my_role = "bottom"
    enemies = [_Enemy("Leona"), _Enemy("Zed")]


def test_fact_sheet_empty_when_disabled(monkeypatch):
    from sylqon import config
    from sylqon.ai import lane_plan

    monkeypatch.setattr(config, "RAG_KIT_MODE", False)
    assert lane_plan._kit_fact_sheet(_Ctx(), {"lane_opponent": {"name": "Leona"}}) == ""


def test_fact_sheet_built_when_enabled(monkeypatch):
    from sylqon import config
    from sylqon.ai import lane_plan
    from sylqon.rag import kit_retrieve as kr

    monkeypatch.setattr(config, "RAG_KIT_MODE", True)
    monkeypatch.setattr(kr, "retrieve_kit_facts", lambda **k: [
        {"champion": "Leona", "slot": "Q", "ability": "Shield of Daybreak", "description": "Stun"}])
    sheet = lane_plan._kit_fact_sheet(_Ctx(), {"lane_opponent": {"name": "Leona"}})
    assert "Shield of Daybreak" in sheet and "CHAMPION ABILITY FACTS" in sheet


def test_fact_sheet_fallback_on_error(monkeypatch):
    from sylqon import config
    from sylqon.ai import lane_plan
    from sylqon.rag import kit_retrieve as kr

    monkeypatch.setattr(config, "RAG_KIT_MODE", True)

    def boom(**k):
        raise RuntimeError("embed down")

    monkeypatch.setattr(kr, "retrieve_kit_facts", boom)
    assert lane_plan._kit_fact_sheet(_Ctx(), {"lane_opponent": {"name": "Leona"}}) == ""
