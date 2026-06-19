"""Offline tests for event-driven gameflow handling.

The gameflow phase pushes a bare phase STRING (not a resource dict) over the
LCU WebSocket; ``_on_gameflow`` must drive ``_handle_phase`` instantly while the
poll loop stays as a safety net. No client, socket, or network.

Run: python -m pytest tests/test_gameflow.py -q
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon.lcu.client import LCUCredentials
from sylqon.lcu.events import GAMEFLOW_TOPIC, LcuEventBus
from sylqon.runtime import PipelineRunner

_EVENT = 8


def _runner():
    """Minimal runner (skip the heavy __init__) with _handle_phase recorded."""
    r = PipelineRunner.__new__(PipelineRunner)
    r.client = object()  # truthy "connected" sentinel
    r._phase_lock = threading.Lock()
    seen: list[str] = []
    r._handle_phase = seen.append  # type: ignore[method-assign]
    return r, seen


def test_on_gameflow_drives_handle_phase():
    r, seen = _runner()
    r._on_gameflow("ChampSelect", "Update")
    r._on_gameflow("InProgress", "Update")
    assert seen == ["ChampSelect", "InProgress"]


def test_on_gameflow_ignores_delete_empty_and_nondict():
    r, seen = _runner()
    r._on_gameflow("EndOfGame", "Delete")
    r._on_gameflow("", "Update")
    r._on_gameflow(None, "Update")
    r._on_gameflow({"phase": "Lobby"}, "Update")  # not a bare string
    assert seen == []


def test_on_gameflow_noop_without_client():
    r, seen = _runner()
    r.client = None
    r._on_gameflow("ChampSelect", "Update")
    assert seen == []


def test_bus_routes_bare_string_phase_payload():
    """The event bus must forward the gameflow event's string ``data`` intact —
    the payload envelope is a dict, but its ``data`` field is a phase string."""
    bus = LcuEventBus(LCUCredentials(port=1, token="t"))
    got: list = []
    bus.subscribe(GAMEFLOW_TOPIC, lambda d, e: got.append((d, e)))
    frame = json.dumps([_EVENT, GAMEFLOW_TOPIC,
                        {"data": "InProgress", "eventType": "Update"}])
    bus._dispatch(frame)
    assert got == [("InProgress", "Update")]
