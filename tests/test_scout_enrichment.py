"""Offline tests for runtime scout-enrichment helpers.

Covers:
  - PipelineRunner._enrich_fingerprint / _name_slug: id-based champion pool
    and comfort entries get name + slug resolved via a fake catalog.
  - PipelineRunner._player_meta: position/side/is_self extraction including
    hidden/anonymized players (no puuid) and is_self detection.
  - _norm_position: 'UTILITY' / 'fill' / '' and every ROLE_ALIASES entry.
  - _scout_players_from_lobby: normalizes /lol-lobby/v1/lobby members.
  - _scout_players_from_session: normalizes myTeam, is_self from cellId,
    anonymized entries (no puuid) produce hidden cards.

No network, no LCU client, no Ollama.

Run: python -m pytest tests/test_scout_enrichment.py -q
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from sylqon.lcu.scout import PlayerFingerprint
from sylqon.runtime import (
    AppState,
    PipelineRunner,
    _norm_position,
    _scout_players_from_lobby,
    _scout_players_from_session,
)

# ------------------------------------------------------------------ catalog stub


class FakeCatalog:
    """Minimal catalog that resolves by Riot integer key only."""

    _MAP = {
        64:  {"name": "Lee Sin", "id": "LeeSin"},
        222: {"name": "Jinx",    "id": "Jinx"},
        103: {"name": "Ahri",    "id": "Ahri"},
    }

    def champion_by_key(self, key):
        return self._MAP.get(int(key) if key is not None else -1)


# ------------------------------------------------------------------ runner builder


def _runner() -> PipelineRunner:
    r = PipelineRunner.__new__(PipelineRunner)
    r.catalog = FakeCatalog()
    r._phase_lock = threading.Lock()
    r.state = AppState()
    return r


# ================================================================== _norm_position


class TestNormPosition:
    def test_empty_string_returns_empty(self):
        assert _norm_position("") == ""

    def test_none_like_returns_empty(self):
        assert _norm_position(None) == ""  # type: ignore[arg-type]

    def test_fill_returns_empty(self):
        assert _norm_position("fill") == ""
        assert _norm_position("FILL") == ""

    def test_unselected_returns_empty(self):
        assert _norm_position("unselected") == ""
        assert _norm_position("UNSELECTED") == ""

    def test_none_string_returns_empty(self):
        assert _norm_position("none") == ""
        assert _norm_position("NONE") == ""

    @pytest.mark.parametrize("raw,expected", [
        ("top",     "top"),
        ("TOP",     "top"),
        ("jungle",  "jungle"),
        ("JUNGLE",  "jungle"),
        ("middle",  "middle"),
        ("mid",     "middle"),
        ("MID",     "middle"),
        ("bottom",  "bottom"),
        ("adc",     "bottom"),
        ("ADC",     "bottom"),
        ("bot",     "bottom"),
        ("utility", "utility"),
        ("UTILITY", "utility"),
        ("support", "utility"),
        ("sup",     "utility"),
    ])
    def test_known_aliases(self, raw, expected):
        assert _norm_position(raw) == expected

    def test_unknown_string_returns_empty(self):
        assert _norm_position("assassin") == ""
        assert _norm_position("marksman") == ""


# ================================================================== _scout_players_from_lobby


class TestScoutPlayersFromLobby:
    def test_empty_members_returns_empty_list(self):
        assert _scout_players_from_lobby({}) == []
        assert _scout_players_from_lobby({"members": []}) == []

    def test_basic_member_fields(self):
        data = {
            "members": [
                {"puuid": "abc-123", "gameName": "Faker",
                 "firstPositionPreference": "middle", "isLocalMember": True},
                {"puuid": "def-456", "summonerName": "Caps",
                 "firstPositionPreference": "UTILITY", "isLocalMember": False},
            ]
        }
        players = _scout_players_from_lobby(data)
        assert len(players) == 2
        assert players[0]["puuid"] == "abc-123"
        assert players[0]["name"] == "Faker"
        assert players[0]["position"] == "middle"
        assert players[0]["is_self"] is True
        assert players[0]["side"] == "ally"

        assert players[1]["puuid"] == "def-456"
        assert players[1]["name"] == "Caps"
        assert players[1]["position"] == "utility"
        assert players[1]["is_self"] is False

    def test_fill_position_normalized_to_empty(self):
        data = {"members": [{"puuid": "x", "gameName": "X",
                              "firstPositionPreference": "fill"}]}
        assert _scout_players_from_lobby(data)[0]["position"] == ""

    def test_missing_puuid_becomes_empty_string(self):
        data = {"members": [{"gameName": "Anon"}]}
        players = _scout_players_from_lobby(data)
        assert players[0]["puuid"] == ""

    def test_gamename_preferred_over_summonername(self):
        data = {"members": [{"puuid": "x", "gameName": "RiotID",
                              "summonerName": "OldName"}]}
        assert _scout_players_from_lobby(data)[0]["name"] == "RiotID"

    def test_summonername_fallback_when_gamename_absent(self):
        data = {"members": [{"puuid": "x", "summonerName": "OldName"}]}
        assert _scout_players_from_lobby(data)[0]["name"] == "OldName"

    def test_none_members_key_returns_empty(self):
        assert _scout_players_from_lobby({"members": None}) == []


# ================================================================== _scout_players_from_session


class TestScoutPlayersFromSession:
    def test_empty_session_returns_empty_list(self):
        assert _scout_players_from_session({}) == []
        assert _scout_players_from_session({"myTeam": []}) == []

    def test_is_self_detected_by_cell_id(self):
        session = {
            "localPlayerCellId": 2,
            "myTeam": [
                {"cellId": 1, "puuid": "p1", "gameName": "A",
                 "assignedPosition": "top"},
                {"cellId": 2, "puuid": "p2", "gameName": "Me",
                 "assignedPosition": "jungle"},
                {"cellId": 3, "puuid": "p3", "gameName": "B",
                 "assignedPosition": "middle"},
            ],
        }
        players = _scout_players_from_session(session)
        assert players[0]["is_self"] is False
        assert players[1]["is_self"] is True
        assert players[2]["is_self"] is False

    def test_anonymized_player_has_empty_puuid(self):
        """Ranked solo anonymizes enemies; the entry is kept so the UI can
        show a hidden card, but puuid is empty so _maybe_scout skips history."""
        session = {
            "localPlayerCellId": 0,
            "myTeam": [
                {"cellId": 0, "assignedPosition": "bottom"},  # no puuid key
            ],
        }
        players = _scout_players_from_session(session)
        assert len(players) == 1
        assert players[0]["puuid"] == ""

    def test_position_normalized(self):
        session = {
            "localPlayerCellId": 0,
            "myTeam": [
                {"cellId": 0, "puuid": "x", "assignedPosition": "UTILITY"},
            ],
        }
        assert _scout_players_from_session(session)[0]["position"] == "utility"

    def test_all_entries_have_side_ally(self):
        session = {
            "localPlayerCellId": 0,
            "myTeam": [{"cellId": 0, "puuid": "x", "gameName": "Y"}],
        }
        assert _scout_players_from_session(session)[0]["side"] == "ally"

    def test_none_my_team_returns_empty(self):
        assert _scout_players_from_session({"localPlayerCellId": 0,
                                            "myTeam": None}) == []


# ================================================================== _player_meta


class TestPlayerMeta:
    def test_basic_extraction(self):
        meta = PipelineRunner._player_meta(
            {"name": "Faker", "position": "middle", "side": "enemy", "is_self": False})
        assert meta == {"name": "Faker", "position": "middle",
                        "side": "enemy", "is_self": False}

    def test_missing_name_defaults_to_hidden(self):
        meta = PipelineRunner._player_meta({})
        assert meta["name"] == "Hidden"

    def test_empty_name_defaults_to_hidden(self):
        meta = PipelineRunner._player_meta({"name": ""})
        assert meta["name"] == "Hidden"

    def test_is_self_truthy_coercion(self):
        assert PipelineRunner._player_meta({"is_self": 1})["is_self"] is True
        assert PipelineRunner._player_meta({"is_self": None})["is_self"] is False


# ================================================================== _enrich_fingerprint / _name_slug


class TestEnrichFingerprint:
    def test_champion_pool_ids_resolved_to_name_and_slug(self):
        r = _runner()
        fp = PlayerFingerprint(
            games_analyzed=8,
            champion_pool=[
                {"champion_id": 64, "games": 6, "wins": 4, "win_rate": 0.67},
                {"champion_id": 222, "games": 2, "wins": 1, "win_rate": 0.50},
            ],
        )
        enriched = r._enrich_fingerprint(fp)
        pool = enriched["champion_pool"]
        assert pool[0]["champion"] == "Lee Sin"
        assert pool[0]["slug"] == "LeeSin"
        assert pool[1]["champion"] == "Jinx"
        assert pool[1]["slug"] == "Jinx"

    def test_comfort_id_resolved(self):
        r = _runner()
        fp = PlayerFingerprint(
            games_analyzed=10,
            comfort={"champion_id": 103, "games": 8, "share": 0.8},
        )
        enriched = r._enrich_fingerprint(fp)
        assert enriched["comfort"]["champion"] == "Ahri"
        assert enriched["comfort"]["slug"] == "Ahri"

    def test_unknown_champion_id_yields_empty_strings(self):
        r = _runner()
        fp = PlayerFingerprint(
            games_analyzed=5,
            champion_pool=[{"champion_id": 9999, "games": 5, "wins": 2, "win_rate": 0.4}],
        )
        enriched = r._enrich_fingerprint(fp)
        assert enriched["champion_pool"][0]["champion"] == ""
        assert enriched["champion_pool"][0]["slug"] == ""

    def test_no_comfort_leaves_none(self):
        r = _runner()
        fp = PlayerFingerprint(games_analyzed=3)
        enriched = r._enrich_fingerprint(fp)
        assert enriched["comfort"] is None

    def test_empty_fingerprint_enriches_without_error(self):
        r = _runner()
        enriched = r._enrich_fingerprint(PlayerFingerprint())
        assert enriched["games_analyzed"] == 0
        assert enriched["champion_pool"] == []
        assert enriched["comfort"] is None

    def test_all_original_fingerprint_fields_preserved(self):
        """Enrichment should not drop fingerprint fields (only adds champion/slug)."""
        r = _runner()
        fp = PlayerFingerprint(
            games_analyzed=6,
            main_role="jungle",
            aggression=0.75,
            avg_cs_per_min=5.2,
            playstyle_tags=["aggressive"],
            champion_pool=[{"champion_id": 64, "games": 6, "wins": 3, "win_rate": 0.5}],
        )
        enriched = r._enrich_fingerprint(fp)
        assert enriched["main_role"] == "jungle"
        assert enriched["aggression"] == 0.75
        assert enriched["avg_cs_per_min"] == 5.2
        assert enriched["playstyle_tags"] == ["aggressive"]


# ================================================================== _hidden_card


class TestHiddenCard:
    def test_hidden_card_sets_hidden_true_and_games_zero(self):
        r = _runner()
        card = r._hidden_card({"name": "Anon", "position": "top", "side": "ally"})
        assert card["hidden"] is True
        assert card["games_analyzed"] == 0
        assert card["name"] == "Anon"
        assert card["position"] == "top"

    def test_hidden_card_with_no_name_defaults_to_hidden(self):
        r = _runner()
        card = r._hidden_card({})
        assert card["name"] == "Hidden"


# ================================================================== _clear_scout


class TestClearScout:
    def test_clear_scout_resets_sig_and_cache_and_state(self):
        r = _runner()
        r._last_scout_sig = "abc|def"
        r._player_scout_cache = {"abc": {"name": "X"}}
        r.state.set("scout", {"players": [{"name": "X"}], "ready": True, "at": 123.0})

        r._clear_scout()

        assert r._last_scout_sig is None
        assert r._player_scout_cache == {}
        snap = r.state.snapshot()["scout"]
        assert snap["players"] == []
        assert snap["ready"] is False
        assert snap["at"] is None
