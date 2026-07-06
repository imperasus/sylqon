"""Offline tests for the hosted-service sync source (opgg_http mirror)."""
from unittest.mock import MagicMock, patch

import pytest
import requests

from sylqon import config
from sylqon.mcp import svc_http

BUNDLE = {
    "patch": "16.13.1",
    "entries": [
        {
            "champion_id": 222, "champion": "Jinx", "role": "BOTTOM",
            "games": 40, "tier": 1, "win_rate": 0.53, "pick_rate": 0.12,
            "payload": {"role": "BOTTOM", "core_item_ids": [3031], "boot_ids": [3006]},
            "counters": [{"champion_id": 119, "opp_winrate": 0.42}],
            "synergies": [{"synergy_champion_id": 412, "win_rate": 0.58, "games": 9}],
        },
        {
            "champion_id": 222, "champion": "Jinx", "role": "MIDDLE",
            "games": 9, "tier": 2, "win_rate": 0.5, "pick_rate": 0.01,
            "payload": None, "counters": [], "synergies": [],
        },
    ],
}


@pytest.fixture(autouse=True)
def reset_cache(monkeypatch):
    monkeypatch.setattr(svc_http, "_BUNDLE", None)
    monkeypatch.setattr(svc_http, "_BUNDLE_AT", 0.0)
    monkeypatch.setattr(config, "SYLQON_META_URL", "http://localhost:8090")


def _resp(json_data):
    r = MagicMock()
    r.raise_for_status.return_value = None
    r.json.return_value = json_data
    return r


def test_disabled_without_url(monkeypatch):
    monkeypatch.setattr(config, "SYLQON_META_URL", "")
    with patch("sylqon.mcp.svc_http.requests.get") as get:
        assert svc_http.available() is False
        get.assert_not_called()


def test_one_bulk_call_serves_all_three():
    with patch("sylqon.mcp.svc_http.requests.get", return_value=_resp(BUNDLE)) as get:
        meta = svc_http.fetch_all_meta()
        payload, counters = svc_http.fetch_detail(222, "bottom")
        synergies = svc_http.fetch_synergies(222, "bottom")
    assert get.call_count == 1  # everything from a single bulk request

    assert 222 in meta
    roles = {p["role"] for p in meta[222]}
    assert roles == {"bottom", "middle"}  # service tokens localized
    bot = next(p for p in meta[222] if p["role"] == "bottom")
    assert bot["tier"] == 1 and bot["win_rate"] == 0.53

    assert payload["core_item_ids"] == [3031]
    assert payload["role"] == "bottom"  # localized for opgg_to_build
    assert counters == [{"champion_id": 119, "opp_winrate": 0.42}]
    assert synergies == [{"synergy_champion_id": 412, "win_rate": 0.58}]


def test_missing_entry_returns_empty():
    with patch("sylqon.mcp.svc_http.requests.get", return_value=_resp(BUNDLE)):
        payload, counters = svc_http.fetch_detail(999, "top")
        assert payload is None and counters == []
        assert svc_http.fetch_synergies(999, "top") == []


def test_network_failure_means_unavailable():
    with patch("sylqon.mcp.svc_http.requests.get",
               side_effect=requests.ConnectionError("down")):
        assert svc_http.available() is False


def test_empty_bundle_means_unavailable():
    with patch("sylqon.mcp.svc_http.requests.get", return_value=_resp({"entries": []})):
        assert svc_http.available() is False
