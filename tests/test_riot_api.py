"""Offline tests for the Riot REST client's match cache + parallel fetch
(sylqon/riot/api.py, sylqon/riot/scout.py::_fetch_matches).

MATCH-V5 objects are immutable once a game ends, so they're cached in-process;
premades share recent games and re-scouts repeat ids, so the cache collapses a
large share of the fetches that dominate live-scout latency. No network: the
network layer (`api._get`) is monkeypatched and its calls counted.

Run: python -m pytest tests/test_riot_api.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon import config
from sylqon.riot import api
from sylqon.riot import scout as rs


def _mid(url: str) -> str:
    return url.rsplit("/", 1)[-1]


def test_get_match_caches_immutable_result(monkeypatch):
    api.clear_match_cache()
    calls: list[str] = []
    monkeypatch.setattr(api, "_get",
                        lambda url, **k: calls.append(_mid(url)) or {"info": {"gameId": _mid(url)}})
    a = api.get_match("EUW1_1")
    b = api.get_match("EUW1_1")
    assert a == b == {"info": {"gameId": "EUW1_1"}}
    assert calls == ["EUW1_1"]   # second call served from cache


def test_get_match_does_not_cache_failures(monkeypatch):
    api.clear_match_cache()
    calls: list[str] = []
    monkeypatch.setattr(api, "_get", lambda url, **k: calls.append(_mid(url)) or None)
    assert api.get_match("EUW1_X") is None
    assert api.get_match("EUW1_X") is None
    assert calls == ["EUW1_X", "EUW1_X"]   # None is left re-fetchable


def test_match_cache_evicts_least_recently_used(monkeypatch):
    api.clear_match_cache()
    monkeypatch.setattr(config, "RIOT_MATCH_CACHE_SIZE", 2)
    monkeypatch.setattr(api, "_get", lambda url, **k: {"u": _mid(url)})
    api.get_match("A")
    api.get_match("B")
    api.get_match("A")   # touch A → now most-recently used
    api.get_match("C")   # over cap → evict the LRU entry (B)
    assert set(api._MATCH_CACHE.keys()) == {"A", "C"}


class _Clock:
    """A controllable stand-in for the `time` module the cache reads."""
    def __init__(self, t: float) -> None:
        self.t = t

    def time(self) -> float:
        return self.t


def test_match_cache_respects_ttl(monkeypatch):
    api.clear_match_cache()
    monkeypatch.setattr(config, "RIOT_MATCH_CACHE_TTL", 100)
    clock = _Clock(1000.0)
    monkeypatch.setattr(api, "time", clock)
    calls: list[str] = []
    monkeypatch.setattr(api, "_get", lambda url, **k: calls.append(_mid(url)) or {"u": _mid(url)})
    api.get_match("A")     # cached at t=1000
    clock.t = 1050.0
    api.get_match("A")     # 50s < TTL → served from cache
    clock.t = 1200.0
    api.get_match("A")     # 200s > TTL → stale → re-fetch
    assert calls == ["A", "A"]


def test_fetch_matches_preserves_order_and_dedups_via_cache(monkeypatch):
    api.clear_match_cache()
    calls: list[str] = []
    monkeypatch.setattr(api, "_get",
                        lambda url, **k: calls.append(_mid(url)) or {"info": {"gameId": _mid(url)}})

    out = rs._fetch_matches(["M1", "M2", "M3"])
    assert [m["info"]["gameId"] for m in out] == ["M1", "M2", "M3"]   # newest-first order kept
    assert sorted(calls) == ["M1", "M2", "M3"]

    calls.clear()
    out2 = rs._fetch_matches(["M2", "M3", "M4"])
    assert [m["info"]["gameId"] for m in out2] == ["M2", "M3", "M4"]
    assert calls == ["M4"]   # M2/M3 from cache; only the new id hit the network


def test_fetch_matches_empty_is_noop():
    assert rs._fetch_matches([]) == []
