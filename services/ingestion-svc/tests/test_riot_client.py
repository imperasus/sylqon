"""Offline tests for the Riot client: mocked HTTP session, recording limiter."""
from unittest.mock import MagicMock

import requests
from app.riot_client import RiotClient


class RecordingLimiter:
    def __init__(self) -> None:
        self.acquires: list[str] = []
        self.penalties: list[tuple[str, float]] = []

    def acquire(self, routing_key: str) -> None:
        self.acquires.append(routing_key)

    def on_rate_limit_exceeded(self, routing_key: str, retry_after: float) -> None:
        self.penalties.append((routing_key, retry_after))


def make_response(status=200, json_data=None, headers=None):
    r = MagicMock()
    r.status_code = status
    r.headers = headers or {}
    r.json.return_value = json_data
    if status >= 400:
        r.raise_for_status.side_effect = requests.HTTPError(f"{status}")
    else:
        r.raise_for_status.return_value = None
    return r


def make_client(responses):
    limiter = RecordingLimiter()
    session = MagicMock()
    session.get.side_effect = responses
    sleeps: list[float] = []
    client = RiotClient(
        rate_limiter=limiter,
        api_key="RGAPI-test",
        mass_region="europe",
        platform_region="eun1",
        session=session,
        sleep=sleeps.append,
    )
    return client, limiter, session, sleeps


def test_ok_response_acquires_permit_first():
    client, limiter, session, _ = make_client([make_response(json_data={"puuid": "p1"})])
    result = client.get_account_by_riot_id("Name", "TAG")
    assert result == {"puuid": "p1"}
    assert limiter.acquires == ["europe"]
    assert session.get.call_args.kwargs["headers"] == {"X-Riot-Token": "RGAPI-test"}


def test_riot_id_is_url_encoded():
    client, _, session, _ = make_client([make_response(json_data={"puuid": "p1"})])
    client.get_account_by_riot_id("Név vagyok", "1#2")
    url = session.get.call_args.args[0]
    assert "N%C3%A9v%20vagyok" in url
    assert "1%232" in url


def test_429_installs_penalty_sleeps_and_retries():
    client, limiter, _, sleeps = make_client(
        [
            make_response(status=429, headers={"Retry-After": "3"}),
            make_response(json_data=["EUN1_1"]),
        ]
    )
    result = client.get_match_ids("puuid-1", count=1)
    assert result == ["EUN1_1"]
    assert limiter.penalties == [("europe", 3.0)]
    assert sleeps == [3.0]
    assert limiter.acquires == ["europe", "europe"]  # re-acquired before the retry


def test_429_without_header_defaults_to_2s():
    client, limiter, _, sleeps = make_client(
        [make_response(status=429), make_response(json_data={"info": {}})]
    )
    client.get_match("EUN1_1")
    assert sleeps == [2.0]
    assert limiter.penalties == [("europe", 2.0)]


def test_404_returns_none_without_retry():
    client, _, session, _ = make_client([make_response(status=404)])
    assert client.get_match("EUN1_missing") is None
    assert session.get.call_count == 1


def test_5xx_exhausts_retries_then_returns_none():
    client, _, session, _ = make_client([make_response(status=500)] * 3)
    assert client.get_timeline("EUN1_1") is None
    assert session.get.call_count == 3  # RIOT_MAX_RETRIES=2 → 3 attempts


def test_connection_error_returns_none():
    limiter = RecordingLimiter()
    session = MagicMock()
    session.get.side_effect = requests.ConnectionError("boom")
    client = RiotClient(rate_limiter=limiter, api_key="k", session=session, sleep=lambda s: None)
    assert client.get_match("EUN1_1") is None


def test_empty_riot_id_short_circuits():
    client, limiter, session, _ = make_client([])
    assert client.get_account_by_riot_id("", "TAG") is None
    assert session.get.call_count == 0
    assert limiter.acquires == []


def test_match_ids_non_list_result_coerced_to_empty():
    client, _, _, _ = make_client([make_response(json_data={"unexpected": True})])
    assert client.get_match_ids("p1") == []


def test_timeline_endpoint_path():
    client, _, session, _ = make_client([make_response(json_data={"info": {"frames": []}})])
    client.get_timeline("EUN1_42")
    assert session.get.call_args.args[0].endswith("/lol/match/v5/matches/EUN1_42/timeline")
    assert "europe.api.riotgames.com" in session.get.call_args.args[0]
