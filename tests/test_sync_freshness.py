"""Offline coverage for the op.gg sync freshness layer:

- patch-aware ``MetaCache.get_build`` / ``refresh_targets`` / ``synced_patch``
- the shared ``_request_json`` retry/backoff helper (mocked session, no network)
- ``fetch_opgg_payload`` routing through that helper

All network is mocked; nothing here touches op.gg or the real cache file.
"""
from __future__ import annotations

import pytest
import requests

import sylqon.cache.opgg_fetch as of
from sylqon.cache.store import MetaCache


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """A MetaCache backed by a throwaway cache file (real seed file is fine)."""
    monkeypatch.setattr("sylqon.config.META_CACHE_PATH", tmp_path / "meta_cache.json")
    return MetaCache()


# --------------------------------------------------------------- patch-aware cache
def test_get_build_is_patch_aware(store):
    build = {"items": [1, 2, 3, 4]}
    store.put_build("Ahri", "middle", build, "opgg", "14.12.1")

    assert store.get_build("Ahri", "middle", "14.12.1")[1] == "cache"
    assert store.get_build("Ahri", "middle", "14.13.1")[1] == "cache-stale"
    # No patch passed -> TTL-only (backwards compatible with the 2-arg callers).
    assert store.get_build("Ahri", "middle")[1] == "cache"


def test_get_build_legacy_entry_without_patch_uses_ttl(store):
    """Entries written before per-build patch tracking have no patch and must
    not be force-staled just because a current_patch is supplied."""
    store.put_build("Ahri", "middle", {"items": [1, 2, 3, 4]}, "opgg", "14.12.1")
    # Simulate a legacy entry by stripping the patch field.
    del store._data["builds"]["Ahri|middle"]["patch"]
    assert store.get_build("Ahri", "middle", "14.99.9")[1] == "cache"


def test_refresh_targets_uses_per_entry_patch(store):
    store.put_build("Ahri", "middle", {"items": [1, 2, 3, 4]}, "opgg", "14.12.1")
    store.track_champion("Ahri", "middle")

    # Same patch -> fresh, so Ahri is not a refresh target.
    assert ("Ahri", "middle") not in store.refresh_targets("14.12.1")
    # Newer patch -> the entry is on an old patch, so it needs refreshing.
    assert ("Ahri", "middle") in store.refresh_targets("14.13.1")


def test_synced_patch_roundtrip(store):
    assert store.get_synced_patch() == ""
    store.set_synced_patch("14.12")
    assert store.get_synced_patch() == "14.12"
    # Persisted to disk: a fresh cache (same monkeypatched path) reads it back.
    assert MetaCache().get_synced_patch() == "14.12"


# ------------------------------------------------------------ _request_json retries
class _FakeResp:
    def __init__(self, json_data=None, status=200):
        self._json = json_data
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self):
        return self._json


def test_request_json_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(of.time, "sleep", lambda *_: None)
    calls = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise requests.ConnectionError("boom")
        return _FakeResp({"data": {"ok": True}})

    monkeypatch.setattr(of._SESSION, "get", fake_get)
    assert of._request_json("http://x", retries=2) == {"data": {"ok": True}}
    assert calls["n"] == 3


def test_request_json_exhausts_retries_returns_none(monkeypatch):
    monkeypatch.setattr(of.time, "sleep", lambda *_: None)
    calls = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        calls["n"] += 1
        raise requests.Timeout("slow")

    monkeypatch.setattr(of._SESSION, "get", fake_get)
    assert of._request_json("http://x", retries=2) is None
    assert calls["n"] == 3  # 1 initial + 2 retries


def test_request_json_does_not_retry_4xx(monkeypatch):
    monkeypatch.setattr(of.time, "sleep", lambda *_: None)
    calls = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        calls["n"] += 1
        return _FakeResp(status=404)

    monkeypatch.setattr(of._SESSION, "get", fake_get)
    assert of._request_json("http://x", retries=3) is None
    assert calls["n"] == 1  # 4xx is terminal


# ------------------------------------------------------------ fetch_opgg_payload path
def test_fetch_opgg_payload_routes_through_request_json(monkeypatch):
    raw = {
        "core_items": [{"ids": [3031]}],
        "boots": [{"ids": [3006]}],
        "starter_items": [{"ids": [1055, 2003]}],
        "summoner_spells": [{"ids": [4, 7]}],
        "runes": [{
            "primary_page_id": 8000, "primary_rune_ids": [8008, 8009, 9103, 8017],
            "secondary_page_id": 8300, "secondary_rune_ids": [8233, 8236],
            "stat_mod_ids": [5005, 5008, 5001],
        }],
        "last_items": [{"ids": [3036]}],
    }
    monkeypatch.setattr(of, "_request_json", lambda url, **kw: {"data": raw})
    payload = of.fetch_opgg_payload(1, "bottom")
    assert payload is not None
    assert payload["core_item_ids"] == [3031]
    assert payload["primary_rune_ids"][0] == 8008


def test_fetch_opgg_payload_unknown_role_skips_fetch(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(of, "_request_json",
                        lambda url, **kw: called.__setitem__("n", called["n"] + 1))
    assert of.fetch_opgg_payload(1, "not-a-role") is None
    assert called["n"] == 0
