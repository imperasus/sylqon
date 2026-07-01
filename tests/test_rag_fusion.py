"""Offline tests for scout + kit fusion (RAG roadmap #3).

Covers:
- _enemy_scout_players filtering (side/hidden/games)
- _behaviour_summary composition
- fuse_enemy_intel: enemy-only, champion join by id, behaviour + kit pointer,
  behavioural-only fallback, empty result
- _scout_fusion_block wiring (RAG on/off + fallback)

No LCU, Ollama, or network required.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon.ai import scout_fusion
from sylqon.rag import kit_index

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

_VOCAB = ["stun", "root", "crowd", "control", "dash", "burst", "poke", "slow", "damage"]


class FakeEmbedder:
    model = "fake-embed"

    def available(self):
        return True

    def embed(self, text):
        if not text:
            return None
        t = text.lower()
        return [float(t.count(w)) for w in _VOCAB]

    def embed_many(self, texts):
        return [self.embed(t) for t in texts]


class Enemy:
    def __init__(self, champion_id, name, role):
        self.champion_id = champion_id
        self.name = name
        self.role = role


class Ctx:
    my_champion = "Caitlyn"
    my_role = "bottom"

    def __init__(self, enemies):
        self.enemies = enemies


def _kit_index():
    kits = {
        "Leona": {"name": "Leona", "passive": {"name": "Sunlight", "description": "bonus damage"},
                  "spells": [
                      {"name": "Shield of Daybreak", "description": "Stun the target crowd control."},
                      {"name": "Eclipse", "description": "Shield durability."},
                      {"name": "Zenith Blade", "description": "Dash and root."},
                      {"name": "Solar Flare", "description": "Area stun crowd control."},
                  ]},
        "Zed": {"name": "Zed", "passive": {"name": "Contempt", "description": "bonus damage low health"},
                "spells": [
                    {"name": "Razor Shuriken", "description": "Poke burst damage."},
                    {"name": "Living Shadow", "description": "Dash reposition."},
                    {"name": "Shadow Slash", "description": "Slow nearby."},
                    {"name": "Death Mark", "description": "Dash burst all-in."},
                ]},
    }
    idx = kit_index.build_kit_index(FakeEmbedder(), kits)
    assert idx is not None
    return idx


def _scout_players():
    return [
        {"side": "enemy", "champion_id": 89, "games_analyzed": 20,
         "playstyle_tags": ["aggressive", "roamer"],
         "comfort": {"champion": "Leona", "share": 0.4},
         "recent_form": {"games": 20, "win_rate": 0.6, "streak": 4},
         "current_champ": {"games": 30, "win_rate": 0.55},
         "premade_partners": ["puuidX"]},
        {"side": "enemy", "champion_id": 238, "games_analyzed": 15,
         "playstyle_tags": ["snowball"],
         "comfort": {"champion": "Zed", "share": 0.7},
         "recent_form": {"games": 15, "win_rate": 0.4, "streak": -2}},
        # filtered out: ally, hidden, zero games
        {"side": "ally", "champion_id": 99, "games_analyzed": 10,
         "comfort": {"champion": "Lux"}},
        {"side": "enemy", "champion_id": 1, "hidden": True, "games_analyzed": 5},
        {"side": "enemy", "champion_id": 2, "games_analyzed": 0},
    ]


def _ctx():
    return Ctx([Enemy(89, "Leona", "utility"), Enemy(238, "Zed", "middle")])


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def test_enemy_filter():
    enemies = scout_fusion._enemy_scout_players(_scout_players())
    ids = {p["champion_id"] for p in enemies}
    assert ids == {89, 238}  # ally / hidden / zero-games excluded


def test_behaviour_summary():
    p = _scout_players()[0]
    s = scout_fusion._behaviour_summary(p)
    assert "plays aggressive, roamer" in s
    assert "mains Leona" in s
    assert "4W streak" in s
    assert "premade (2-stack)" in s


def test_behaviour_summary_empty():
    assert scout_fusion._behaviour_summary({}) == ""


# ---------------------------------------------------------------------------
# fuse_enemy_intel
# ---------------------------------------------------------------------------

def test_fuse_with_kit_includes_behaviour_and_ability():
    block = scout_fusion.fuse_enemy_intel(
        _ctx(), _scout_players(), kit_index=_kit_index(), embedder=FakeEmbedder())
    assert "SCOUTED ENEMY PLAYERS" in block
    assert "utility Leona" in block and "middle Zed" in block
    assert "aggressive" in block
    assert "watch Leona's" in block  # kit pointer appended
    assert "Lux" not in block  # ally excluded


def test_fuse_behavioural_only_without_kit():
    block = scout_fusion.fuse_enemy_intel(_ctx(), _scout_players(), kit_index=None)
    assert "Leona" in block
    assert "watch" not in block  # no kit pointer


def test_fuse_empty_without_enemy_scout():
    allies_only = [{"side": "ally", "champion_id": 99, "games_analyzed": 10}]
    assert scout_fusion.fuse_enemy_intel(_ctx(), allies_only) == ""
    assert scout_fusion.fuse_enemy_intel(_ctx(), None) == ""


def test_fuse_falls_back_to_comfort_when_not_in_ctx():
    # enemy champion_id not present among ctx.enemies → use comfort champion
    ctx = Ctx([])
    players = [{"side": "enemy", "champion_id": 777, "games_analyzed": 10,
                "comfort": {"champion": "Ahri", "share": 0.5},
                "playstyle_tags": ["aggressive"]}]
    block = scout_fusion.fuse_enemy_intel(ctx, players)
    assert "Ahri" in block


# ---------------------------------------------------------------------------
# _scout_fusion_block wiring (lane_plan)
# ---------------------------------------------------------------------------

def test_block_empty_when_disabled(monkeypatch):
    from sylqon import config
    from sylqon.ai import lane_plan

    monkeypatch.setattr(config, "RAG_FUSION_MODE", False)
    assert lane_plan._scout_fusion_block(_ctx(), _scout_players()) == ""


def test_block_built_when_enabled(monkeypatch):
    from sylqon import config
    from sylqon.ai import lane_plan

    monkeypatch.setattr(config, "RAG_FUSION_MODE", True)
    # avoid the kit-index disk read; force behavioural-only
    monkeypatch.setattr("sylqon.rag.item_index.load_index", lambda path=None: None)
    block = lane_plan._scout_fusion_block(_ctx(), _scout_players())
    assert "SCOUTED ENEMY PLAYERS" in block and "Leona" in block


def test_block_fallback_on_error(monkeypatch):
    from sylqon import config
    from sylqon.ai import lane_plan

    monkeypatch.setattr(config, "RAG_FUSION_MODE", True)

    def boom(*a, **k):
        raise RuntimeError("kit index read failed")

    monkeypatch.setattr("sylqon.rag.item_index.load_index", boom)
    assert lane_plan._scout_fusion_block(_ctx(), _scout_players()) == ""
