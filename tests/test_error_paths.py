"""Error-path & diagnostics coverage.

The pipeline's failure handling and the new ``/api/debug/*`` endpoints had no
offline coverage — the happy path was tested but "what happens when Ollama is
down / the DB errors / an endpoint raises" was not. These tests exercise those
paths without any network, LCU or Ollama, monkeypatching the external
touchpoints so the diagnostics contract is pinned.
"""
from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace

from sylqon import config, server


# --------------------------------------------------------------------------- #
# /api/debug/config — effective config, no secret leakage
# --------------------------------------------------------------------------- #
def test_debug_config_reports_keys_without_leaking_secrets(monkeypatch):
    monkeypatch.setattr(config, "RIOT_API_KEY", "RGAPI-super-secret", raising=False)
    out = server.debug_config()

    assert out["log_level"] == config.LOG_LEVEL
    assert out["ollama_url"] == config.OLLAMA_URL
    # The key itself is never echoed — only its presence.
    assert out["riot_api_key_set"] is True
    assert "RGAPI-super-secret" not in json.dumps(out)

    monkeypatch.setattr(config, "RIOT_API_KEY", "", raising=False)
    assert server.debug_config()["riot_api_key_set"] is False


# --------------------------------------------------------------------------- #
# /api/debug/logs — in-memory feed filtering
# --------------------------------------------------------------------------- #
def test_debug_logs_filters_by_level_and_limit(monkeypatch):
    events = [
        {"ts": 1, "level": "info", "msg": "a"},
        {"ts": 2, "level": "warning", "msg": "b"},
        {"ts": 3, "level": "error", "msg": "c"},
        {"ts": 4, "level": "info", "msg": "d"},
    ]
    monkeypatch.setattr(server.runner.state, "snapshot", lambda: {"events": list(events)})

    all_events = server.debug_logs()
    assert all_events["count"] == 4

    only_errors = server.debug_logs(level="error")
    assert only_errors["count"] == 1
    assert only_errors["events"][0]["msg"] == "c"

    limited = server.debug_logs(limit=2)
    assert limited["count"] == 2
    assert [e["msg"] for e in limited["events"]] == ["c", "d"]


# --------------------------------------------------------------------------- #
# /api/debug/health — runtime re-probe, graceful when deps are down
# --------------------------------------------------------------------------- #
class _FakeQuery:
    def limit(self, _n):
        return self

    def all(self):
        return []


class _FakeSession:
    def __init__(self):
        self.closed = False

    def query(self, _model):
        return _FakeQuery()

    def close(self):
        self.closed = True


def _patch_health_deps(monkeypatch, *, ollama, opgg_ok, db_ok):
    monkeypatch.setattr(server.runner.engine, "available", lambda: ollama)
    monkeypatch.setattr(
        server.runner.state, "snapshot",
        lambda: {"lcu": {"connected": True}, "cache": {"builds": 7}},
    )
    if db_ok:
        monkeypatch.setattr(server, "get_session", lambda: _FakeSession())
    else:
        def _boom():
            raise RuntimeError("db unavailable")
        monkeypatch.setattr(server, "get_session", _boom)

    import requests
    def _fake_get(*_a, **_k):
        if opgg_ok:
            return SimpleNamespace(status_code=200)
        raise requests.RequestException("op.gg unreachable")
    monkeypatch.setattr(requests, "get", _fake_get)


def test_debug_health_all_up(monkeypatch):
    _patch_health_deps(monkeypatch, ollama=True, opgg_ok=True, db_ok=True)
    out = server.debug_health()

    assert out["ok"] is True
    assert out["lcu"]["connected"] is True
    assert out["ollama"]["available"] is True
    assert out["opgg"]["reachable"] is True
    assert out["database"]["ok"] is True
    assert out["cache"]["builds"] == 7


def test_debug_health_degrades_without_raising(monkeypatch):
    # Every dependency down: the endpoint must report false, never throw.
    _patch_health_deps(monkeypatch, ollama=False, opgg_ok=False, db_ok=False)
    out = server.debug_health()

    assert out["ok"] is False
    assert out["ollama"]["available"] is False
    assert out["opgg"]["reachable"] is False
    assert out["database"]["ok"] is False


def test_debug_health_survives_ollama_probe_exception(monkeypatch):
    _patch_health_deps(monkeypatch, ollama=True, opgg_ok=True, db_ok=True)

    def _raise():
        raise ConnectionError("ollama exploded")
    monkeypatch.setattr(server.runner.engine, "available", _raise)

    out = server.debug_health()  # must not propagate
    assert out["ollama"]["available"] is False


# --------------------------------------------------------------------------- #
# Global exception handler — structured 500 with trace id
# --------------------------------------------------------------------------- #
def test_unhandled_exception_returns_structured_500():
    request = SimpleNamespace(
        state=SimpleNamespace(trace_id="abc123"),
        method="GET",
        url=SimpleNamespace(path="/api/boom"),
    )
    resp = asyncio.run(server._unhandled_exception(request, ValueError("kaboom")))

    assert resp.status_code == 500
    body = json.loads(resp.body)
    assert body["error"] == "ValueError"
    assert body["detail"] == "kaboom"
    assert body["trace_id"] == "abc123"


# --------------------------------------------------------------------------- #
# logging_setup — idempotent config + JSON formatter
# --------------------------------------------------------------------------- #
def test_setup_logging_is_idempotent():
    from sylqon import logging_setup

    logging_setup.setup_logging(force=True)
    before = len(logging.getLogger().handlers)
    logging_setup.setup_logging(force=True)
    after = len(logging.getLogger().handlers)
    assert before == after  # force replaces, never stacks


def test_json_formatter_emits_valid_json():
    from sylqon.logging_setup import _JsonFormatter

    rec = logging.LogRecord("sylqon.test", logging.WARNING, __file__, 1, "hello %s", ("world",), None)
    line = _JsonFormatter().format(rec)
    parsed = json.loads(line)
    assert parsed["level"] == "WARNING"
    assert parsed["msg"] == "hello world"
    assert parsed["logger"] == "sylqon.test"
