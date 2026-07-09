"""Profile assembly tests — mocked Riot client, fully offline."""
from app import profile


class FakeRiot:
    """Minimal RiotClient surface build_profile depends on; any slice can be None."""

    def __init__(self, account=None, summoner=None, ranked=None, mastery=None):
        self._account, self._summoner = account, summoner
        self._ranked, self._mastery = ranked, mastery

    def get_account_by_riot_id(self, game_name, tag_line):
        return self._account

    def get_summoner_by_puuid(self, puuid):
        return self._summoner

    def get_ranked_stats(self, puuid):
        return self._ranked

    def get_top_mastery(self, puuid, count=6):
        return self._mastery


def test_build_profile_composes_all_sources():
    riot = FakeRiot(
        account={"puuid": "P1", "gameName": "Faker", "tagLine": "KR1"},
        summoner={"summonerLevel": 800, "profileIconId": 5},
        ranked=[
            {"queueType": "RANKED_SOLO_5x5", "tier": "CHALLENGER", "rank": "I",
             "leaguePoints": 1200, "wins": 300, "losses": 200},
            {"queueType": "RANKED_FLEX_SR", "tier": "DIAMOND", "rank": "II",
             "leaguePoints": 50, "wins": 10, "losses": 5},
        ],
        mastery=[
            {"championId": 266, "championPoints": 500000, "championLevel": 7},
            {"championId": 62, "championPoints": 250000, "championLevel": 6},
        ],
    )
    p = profile.build_profile(riot, "Faker", "KR1")
    assert p["riot_id"] == "Faker#KR1"
    assert p["summoner_level"] == 800
    assert p["profile_icon_url"].endswith("/img/profileicon/5.png")
    # solo before flex; winrate computed (300/500 = 60%)
    assert [r["queue"] for r in p["ranked"]] == ["RANKED_SOLO_5x5", "RANKED_FLEX_SR"]
    assert p["ranked"][0]["winrate"] == 60
    # champion names resolved from the bundled catalog, incl. key!=name (Wukong=62)
    assert [c["name"] for c in p["top_champions"]] == ["Aatrox", "Wukong"]
    assert p["top_champions"][0]["square_url"].endswith("/img/champion/Aatrox.png")
    assert p["top_champions"][1]["square_url"].endswith("/img/champion/MonkeyKing.png")


def test_build_profile_none_when_account_missing():
    assert profile.build_profile(FakeRiot(account=None), "Nobody", "XXX") is None


def test_build_profile_degrades_on_partial_failures():
    # Account resolves, but every detail call returns None (transient) → empty
    # slices, never a crash.
    riot = FakeRiot(account={"puuid": "P1", "gameName": "A", "tagLine": "B"})
    p = profile.build_profile(riot, "A", "B")
    assert p is not None
    assert p["summoner_level"] is None
    assert p["ranked"] == []
    assert p["top_champions"] == []
