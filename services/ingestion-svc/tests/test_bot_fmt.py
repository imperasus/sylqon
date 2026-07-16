"""Presentation tests for the /pool embed text (pure function in bot.py)."""
from app.bot import build_pool_embed_text

REPORT = {
    "puuid": "p",
    "roles": {
        "BOTTOM": {
            "games": 21,
            "current": [],
            "coverage_score": 64,
            "components": {"performance": 65, "blind_safety": 25, "counter_coverage": 100},
            "low_data": False,
            "suggested": [
                {"champion": "Jhin", "reasons": ["comfort"], "personal": {"games": 9, "wins": 7}},
                {"champion": "Swain", "reasons": ["meta-presence"], "personal": None},
            ],
            "uncovered": ["Draven"],
        },
        "MIDDLE": {
            "games": 1,
            "current": [],
            "coverage_score": 50,
            "components": {"performance": 50, "blind_safety": 50, "counter_coverage": 50},
            "low_data": True,
            "suggested": [],
            "uncovered": [],
        },
    },
}


def test_pool_embed_text_hu():
    text = build_pool_embed_text(REPORT, "hu")
    assert "BOTTOM · 21 meccs" in text
    assert "**64**" in text
    assert "**Jhin** (komfort)" in text
    assert "Draven" in text
    assert "kevés adat" in text  # MIDDLE low_data warning


def test_pool_embed_text_en():
    text = build_pool_embed_text(REPORT, "en")
    assert "BOTTOM · 21 games" in text
    assert "**Jhin** (comfort)" in text
    assert "thin data" in text
    assert text != build_pool_embed_text(REPORT, "hu")


def test_pool_embed_respects_max_roles():
    text = build_pool_embed_text(REPORT, "hu", max_roles=1)
    assert "MIDDLE" not in text
