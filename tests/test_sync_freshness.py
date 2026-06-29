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


def test_bulk_put_builds(store):
    """Full-sync pre-warm path: many builds in one save, raw_payload optional,
    counted by stats() and persisted to disk."""
    items = [
        ("Ahri", "middle", {"items": [1, 2, 3, 4]}, {"shaped": "payload"}),
        ("Jinx", "bottom", {"items": [5, 6, 7, 8]}, None),
    ]
    n = store.bulk_put_builds(items, "14.12.1")

    assert n == 2
    assert store.stats()["builds"] == 2
    # Tagged source="opgg" + patch-fresh -> a "cache" hit, not stale.
    assert store.get_build("Ahri", "middle", "14.12.1")[1] == "cache"
    # raw_payload kept when given (so reconvert can refresh after a catalog
    # supplement), absent when None.
    assert store._data["builds"]["Ahri|middle"]["raw_payload"] == {"shaped": "payload"}
    assert "raw_payload" not in store._data["builds"]["Jinx|bottom"]
    # Persisted: a fresh cache on the same (monkeypatched) path reads them back.
    assert MetaCache().stats()["builds"] == 2


def test_bulk_put_builds_empty_is_noop(store):
    assert store.bulk_put_builds([], "14.12.1") == 0
    assert store.stats()["builds"] == 0


def test_bulk_put_builds_skip_existing_preserves_fresher_entries(store):
    """The startup DB backfill only fills gaps — it must never clobber an already
    cached (e.g. fresher live-fetched) build."""
    live = {"items": [9, 9, 9, 9]}
    store.put_build("Ahri", "middle", live, "opgg", "14.12.1")

    added = store.bulk_put_builds(
        [("Ahri", "middle", {"items": [1, 1, 1, 1]}, None),   # already present -> skipped
         ("Jinx", "bottom", {"items": [2, 2, 2, 2]}, None)],  # missing -> added
        "14.12.1", skip_existing=True)

    assert added == 1
    assert store.stats()["builds"] == 2
    assert store.get_build("Ahri", "middle")[0] == live  # untouched
    assert store.get_build("Jinx", "bottom")[0] == {"items": [2, 2, 2, 2]}


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
