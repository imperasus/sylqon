"""Offline tests for the hosted-service build fetcher (op.gg replacement path).

No network: requests is mocked; the feature is off by default (empty
SYLQON_META_URL) so the local product's behaviour is unchanged unless opted in.
"""
from unittest.mock import MagicMock, patch

import requests

from sylqon import config
from sylqon.cache.svc_fetch import fetch_sylqon_payload

PAYLOAD = {
    "role": "BOTTOM",
    "core_item_ids": [3031, 3094, 3036],
    "boot_ids": [3006],
    "starter_item_ids": [1055],
    "primary_page_id": 8000,
    "primary_rune_ids": [8008, 9101, 9104, 8014],
    "secondary_page_id": 8100,
    "secondary_rune_ids": [8139, 8135],
    "stat_mod_ids": [5005, 5008, 5001],
    "summoner_spell_ids": [4, 7],
    "summoner_spell_options": [4, 7, 21],
    "skill_order": ["Q", "W", "E"],
}


def _response(status=200, json_data=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_data
    r.raise_for_status.return_value = None
    return r


def test_disabled_without_url(monkeypatch):
    monkeypatch.setattr(config, "SYLQON_META_URL", "")
    with patch("sylqon.cache.svc_fetch.requests.get") as get:
        assert fetch_sylqon_payload("Jinx", "bottom") is None
        get.assert_not_called()


def test_success_keeps_local_role(monkeypatch):
    monkeypatch.setattr(config, "SYLQON_META_URL", "http://localhost:8090")
    with patch("sylqon.cache.svc_fetch.requests.get",
               return_value=_response(json_data=dict(PAYLOAD))) as get:
        payload = fetch_sylqon_payload("Jinx", "bottom")
    assert payload is not None
    assert payload["core_item_ids"] == [3031, 3094, 3036]
    assert payload["role"] == "bottom"  # local role string preserved
    url = get.call_args.args[0]
    assert url == "http://localhost:8090/api/meta-build/Jinx"
    assert get.call_args.kwargs["params"] == {"role": "bottom"}


def test_404_returns_none(monkeypatch):
    monkeypatch.setattr(config, "SYLQON_META_URL", "http://localhost:8090")
    with patch("sylqon.cache.svc_fetch.requests.get", return_value=_response(status=404)):
        assert fetch_sylqon_payload("Jinx", "bottom") is None


def test_unusable_payload_returns_none(monkeypatch):
    monkeypatch.setattr(config, "SYLQON_META_URL", "http://localhost:8090")
    with patch("sylqon.cache.svc_fetch.requests.get",
               return_value=_response(json_data={"role": "BOTTOM", "core_item_ids": []})):
        assert fetch_sylqon_payload("Jinx", "bottom") is None


def test_network_error_returns_none(monkeypatch):
    monkeypatch.setattr(config, "SYLQON_META_URL", "http://localhost:8090")
    with patch("sylqon.cache.svc_fetch.requests.get",
               side_effect=requests.ConnectionError("boom")):
        assert fetch_sylqon_payload("Jinx", "bottom") is None
