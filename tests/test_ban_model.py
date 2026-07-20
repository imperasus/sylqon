"""F3 — multi-factor, team-wide ban model.

Unit-tests the pure scoring/categorization and an integration pass through the
runner that proves a meta-warping pick is labelled a *power* ban while a
pool-beater is labelled a *personal* ban, and that candidates are gathered
across all lanes (not just the player's).
"""
from __future__ import annotations

from sylqon.analysis import ban_model
from sylqon.runtime import PipelineRunner


# -- pure scoring / categorization -------------------------------------------
def test_s_tier_no_pool_threat_is_a_power_ban():
    total, factors = ban_model.score_ban(
        tier=0, pick_rate=15.0, pool_threat=0.0, is_flex=False, plays_my_role=True)
    assert ban_model.categorize(factors) == "power"
    assert factors["meta"] == 1.0
    assert total > 0.4


def test_pool_beater_is_a_personal_ban():
    total, factors = ban_model.score_ban(
        tier=2, pick_rate=5.0, pool_threat=9.0, is_flex=False, plays_my_role=True)
    assert ban_model.categorize(factors) == "personal"
    assert factors["pool_counter"] > 0.8


def test_off_role_champion_has_no_pool_factor():
    # It can't fight the player's pick, so a big pool advantage doesn't count.
    _, factors = ban_model.score_ban(
        tier=2, pick_rate=5.0, pool_threat=9.0, is_flex=False, plays_my_role=False)
    assert factors["pool_counter"] == 0.0
    assert ban_model.categorize(factors) != "personal"


def test_flex_and_contested_raise_the_score():
    base, _ = ban_model.score_ban(3, 2.0, 0.0, is_flex=False, plays_my_role=True)
    flexed, _ = ban_model.score_ban(3, 2.0, 0.0, is_flex=True, plays_my_role=True)
    contested, _ = ban_model.score_ban(3, 12.0, 0.0, is_flex=False, plays_my_role=True)
    assert flexed > base
    assert contested > base


def test_reason_leads_with_category():
    _, f_power = ban_model.score_ban(0, 15.0, 0.0, False, True)
    assert ban_model.ban_reason("Zed", 0, f_power, "power", False, False).startswith("Power ban")
    _, f_personal = ban_model.score_ban(2, 5.0, 9.0, False, True)
    assert ban_model.ban_reason("Draven", 2, f_personal, "personal", False, False) \
        .startswith("Bans for you")


# -- integration through the runner ------------------------------------------
class _Ctx:
    my_role = "bottom"
    my_champion = "Caitlyn"
    enemies: list = []
    allies: list = []
    bans: list = []


def test_ban_suggestions_labels_power_vs_personal(monkeypatch):
    r = PipelineRunner()
    # Team-wide meta: an S+ toplaner (off my role) and an A-tier botlaner that
    # happens to beat my pool.
    monkeypatch.setattr(r, "_meta_positions", lambda: {
        "top": [{"champion": "Darius", "slug": "Darius", "tier": 0,
                 "win_rate": 53.0, "pick_rate": 14.0}],
        "bottom": [{"champion": "Draven", "slug": "Draven", "tier": 2,
                    "win_rate": 51.0, "pick_rate": 6.0}],
    })
    monkeypatch.setattr(r, "_db_role_rows", lambda role: [])  # no DB needed
    monkeypatch.setattr(r.store, "get_pool", lambda: {"bottom": ["Jinx"]})
    monkeypatch.setattr(r, "_pool_counter_threat", lambda role, pool: {"Draven": 8.0})

    out = r._ban_suggestions(_Ctx(), limit=5)
    by_name = {b["name"]: b for b in out}

    # Both surface even though Darius is off my role (team-wide gathering).
    assert "Darius" in by_name and "Draven" in by_name
    assert by_name["Darius"]["category"] == "power"
    assert by_name["Draven"]["category"] == "personal"
    assert by_name["Draven"]["counters_pool"] == 8.0
    assert "factors" in by_name["Darius"]


def test_ban_suggestions_empty_when_no_source(monkeypatch):
    r = PipelineRunner()
    monkeypatch.setattr(r, "_meta_positions", lambda: {})
    monkeypatch.setattr(r, "_db_role_rows", lambda role: [])
    assert r._ban_suggestions(_Ctx()) == []
