"""Offline tests for the profile coaching-insights aggregation.

The ``factory`` fixture comes from tests/conftest.py.
"""
from app import insights, store
from tests.test_matches import ME, _match


def _seed(factory, *specs):
    with factory() as s:
        for match_id, created, win in specs:
            store.insert_match_bundle(s, _match(match_id, created, ME, win),
                                      {"info": {"frames": []}}, region="europe")


def test_insights_aggregates_recent_matches(factory):
    _seed(factory, ("EUN1_1", 1000, True), ("EUN1_2", 2000, False), ("EUN1_3", 3000, True))
    with factory() as s:
        ins = insights.build_insights(s, ME)
    assert ins["games"] == 3
    assert ins["wins"] == 2 and ins["winrate"] == 67
    # every seeded game is 3/2/7 → (9+21)/6 = 5.0
    assert ins["kda"] == 5.0
    assert ins["avg_cs_per_min"] == 6.3  # 190 CS / 30 min per game
    assert ins["avg_vision"] == 25
    assert ins["recent_form"] == {"games": 3, "wins": 2}
    assert ins["top_champions"][0]["champion"] == "Aatrox"
    assert ins["top_champions"][0]["games"] == 3


def test_insights_none_without_stored_matches(factory):
    with factory() as s:
        assert insights.build_insights(s, "puuid-unknown") is None


def test_lesson_failure_keeps_aggregates(factory, monkeypatch):
    _seed(factory, ("EUN1_1", 1000, True))

    def boom(*a, **k):
        raise RuntimeError("advice exploded")

    import app.advice.pipeline as pipeline
    monkeypatch.setattr(pipeline, "get_or_generate_advice", boom)
    with factory() as s:
        ins = insights.build_insights(s, ME)
    assert ins is not None and ins["games"] == 1
    assert ins["lesson"] is None  # advice failure never breaks the profile