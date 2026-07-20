"""F5 — mastery-weighted comfort (one-trick detection).

Mastery is a strong "can the player pilot this?" signal that op.gg/Blitz ignore.
It lifts a mained champion's comfort even off a thin recent sample, but never
drags a strong recent win-rate down.
"""
from __future__ import annotations

from types import SimpleNamespace

from sylqon.analysis.scoring import ChampionScorer, mastery_comfort


def _comfort(name, pool, personal):
    return ChampionScorer()._comfort_score(name, pool, personal)


# -- mastery floor -----------------------------------------------------------
def test_mastery_comfort_scales_with_points():
    assert mastery_comfort(None) == 0.0
    assert mastery_comfort(500) == 0.0            # negligible mastery
    assert mastery_comfort(60_000) > mastery_comfort(25_000)
    assert mastery_comfort(300_000) == 90.0


# -- comfort integration -----------------------------------------------------
def test_one_trick_off_pool_beats_baseline():
    # A 250k-point main the player hasn't logged recent tracked games on is far
    # more comfortable than a cold off-pool champion.
    otp = _comfort("Yasuo", set(), {"Yasuo": {"games": 0, "mastery_points": 250_000}})
    cold = _comfort("Ahri", set(), {})
    assert otp >= 84.0
    assert otp > cold


def test_mastery_never_lowers_a_strong_recent_winrate():
    # High recent win-rate in pool, but low mastery points → comfort stays high.
    stats = {"Jinx": {"games": 40, "win_rate": 0.62, "mastery_points": 3_000}}
    assert _comfort("Jinx", {"Jinx"}, stats) >= 90.0


def test_no_mastery_is_backward_compatible():
    # Without mastery data the score is exactly the old pool/off-pool baseline.
    assert _comfort("Ahri", {"Ahri"}, {}) == 68.0     # COMFORT_IN_POOL
    assert _comfort("Ahri", set(), {}) == 42.0         # COMFORT_OFF_POOL


# -- runtime merge -----------------------------------------------------------
def test_merge_self_mastery_adds_mastery_only_champs(monkeypatch):
    from sylqon.runtime import PipelineRunner
    r = PipelineRunner()
    monkeypatch.setattr(r, "_riot_self_puuid", lambda: "puuid-123")
    monkeypatch.setattr(r.catalog, "champion_by_key",
                        lambda cid: {103: {"name": "Ahri"}, 157: {"name": "Yasuo"}}.get(cid))
    import sylqon.riot.api as api
    monkeypatch.setattr(api, "get_top_mastery", lambda pu, count=20: [
        {"championId": 157, "championPoints": 300_000, "championLevel": 7},
        {"championId": 103, "championPoints": 40_000, "championLevel": 6},
    ])
    named: dict = {"Ahri": {"games": 8, "wins": 5, "win_rate": 0.625}}
    r._merge_self_mastery(named)
    assert named["Ahri"]["mastery_points"] == 40_000     # augmented existing
    assert named["Yasuo"]["mastery_points"] == 300_000   # mastery-only, games 0
    assert named["Yasuo"]["games"] == 0


def test_merge_self_mastery_noop_without_puuid(monkeypatch):
    from sylqon.runtime import PipelineRunner
    r = PipelineRunner()
    monkeypatch.setattr(r, "_riot_self_puuid", lambda: "")
    named = {"Ahri": {"games": 8, "wins": 5, "win_rate": 0.625}}
    r._merge_self_mastery(named)
    assert "mastery_points" not in named["Ahri"]
