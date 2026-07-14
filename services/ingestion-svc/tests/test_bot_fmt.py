"""Presentation tests for the bot's pure embed builders + daily-puzzle targeting."""
from app.bot import build_daily_puzzle_payload, build_pool_embed_text, daily_puzzle_targets
from app.models import DailyPuzzle, GuildConfig, Match, PuzzleDelivery

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


# -- Daily Draft embed --------------------------------------------------------
PUZZLE = {
    "role": "JUNGLE", "role_label": "Jungle", "side": "red",
    "ally": [{"name": n, "slug": n} for n in ("Aatrox", "Zed", "Locke", "Swain")],
    "enemy": [{"name": n, "slug": n}
              for n in ("Sett", "Jayce", "Galio", "Miss Fortune", "Seraphine")],
    "enemy_comp": {"label": "Teamfight / Wombo"},
    "candidates": [{"name": n}
                   for n in ("Amumu", "Briar", "Master Yi", "Jarvan IV", "Viego", "Shyvana")],
    "match": {"queue_id": 420, "patch": "16.13", "rank_band": "GOLD"},
}


def test_daily_puzzle_embed_hu():
    p = build_daily_puzzle_payload(PUZZLE, "2026-07-15", "hu")
    assert "Napi Draft — 2026-07-15" in p["title"]
    assert "**Jungle**" in p["description"] and "piros" in p["description"]
    assert "Teamfight / Wombo" in p["description"]
    assert "sylqon.com/daily" in p["description"]
    team = p["fields"][0]["value"]
    assert "❓ (te)" in team  # the hidden slot is the reader's
    assert "Top — **Aatrox**" in team and "Support — **Swain**" in team
    assert "Sett" in p["fields"][1]["value"]
    assert "Amumu · Briar" in p["fields"][2]["value"]
    assert p["footer"]["text"] == "Ranked Solo/Duo · patch 16.13 · Gold"
    # spoiler-free: the teaser must never leak tiers or the answer markers
    dumped = str(p).lower()
    for word in ("strong", "solid", "risky", "real pick", "engine's read on it"):
        assert word not in dumped


def test_daily_puzzle_embed_en_differs():
    p = build_daily_puzzle_payload(PUZZLE, "2026-07-15", "en")
    assert "Daily Draft — 2026-07-15" in p["title"]
    assert "red side" in p["description"]
    assert "❓ (you)" in p["fields"][0]["value"]
    assert p != build_daily_puzzle_payload(PUZZLE, "2026-07-15", "hu")


def test_daily_puzzle_targets_and_dedupe(factory):
    day = "2026-07-15"
    with factory() as s:
        s.add(Match(match_id="M1", platform="eun1", region="europe", raw={}))
        s.add(DailyPuzzle(puzzle_date=day, match_id="M1", payload=PUZZLE))
        s.add(GuildConfig(guild_id=1, reports_channel_id=111, lang="hu"))
        s.add(GuildConfig(guild_id=2, advice_channel_id=222, lang="en"))
        s.add(GuildConfig(guild_id=3))  # no channel configured -> never targeted
        s.commit()

        got = {(g, c, lang) for g, c, lang, _ in daily_puzzle_targets(s, day)}
        assert got == {(1, 111, "hu"), (2, 222, "en")}  # reports wins, advice is the fallback

        s.add(PuzzleDelivery(guild_id=1, puzzle_date=day))
        s.commit()
        assert {g for g, *_ in daily_puzzle_targets(s, day)} == {2}

        assert daily_puzzle_targets(s, "1999-01-01") == []  # no puzzle -> nothing due
