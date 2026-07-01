"""Offline tests for PipelineRunner._handle_phase phase-transition matrix.

Builds a minimal runner via __new__ (skips the heavy __init__) with only the
attributes _handle_phase touches. Asserts that each phase drives the right
ensure/stop/clear helpers and updates ``lcu.phase``. Also verifies the lock
serializes concurrent callers.

Run: python -m pytest tests/test_handle_phase.py -q
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from sylqon.runtime import AppState, PipelineRunner

# ------------------------------------------------------------------ helpers

_RMC_PATH = "sylqon.runtime.read_match_context"


def _make_runner(demo: bool = False) -> tuple[PipelineRunner, dict[str, list]]:
    """Build a minimal PipelineRunner via __new__ and replace every side-effecting
    method that _handle_phase calls with a stub that appends its name to a log.

    ``read_match_context`` is patched at module level to return None so the
    ChampSelect branch doesn't need a real catalog/client.  Each test that
    needs specific ChampSelect context can patch it separately."""
    r = PipelineRunner.__new__(PipelineRunner)
    r.client = object()       # truthy "connected" sentinel
    r._phase_lock = threading.Lock()
    r._summoner_id = 0
    r._event_bus = None       # falsy → bus_ok is False in ChampSelect
    r.catalog = object()      # truthy sentinel; read_match_context is mocked away
    r.state = AppState()
    if demo:
        r.state.set("demo", True)

    log: dict[str, list] = {
        "stop_live_poller": [], "ensure_live_poller": [],
        "stop_event_bus": [], "ensure_event_bus": [],
        "clear_post_game": [], "clear_scout": [],
        "reset_draft_state": [], "retry_injection_if_pending": [],
        "publish_lobby": [], "maybe_recommend": [],
    }

    r._stop_live_poller = lambda: log["stop_live_poller"].append(1)  # type: ignore
    r._ensure_live_poller = lambda: log["ensure_live_poller"].append(1)  # type: ignore
    r._stop_event_bus = lambda: log["stop_event_bus"].append(1)  # type: ignore
    # _ensure_event_bus must set _event_bus to None (not running) so the
    # bus_ok check in ChampSelect falls through to read_match_context.
    def _fake_ensure_event_bus():
        log["ensure_event_bus"].append(1)
        r._event_bus = None
    r._ensure_event_bus = _fake_ensure_event_bus  # type: ignore
    r._clear_post_game = lambda: log["clear_post_game"].append(1)  # type: ignore
    r._clear_scout = lambda: log["clear_scout"].append(1)  # type: ignore
    r._reset_draft_state = lambda: log["reset_draft_state"].append(1)  # type: ignore
    r._retry_injection_if_pending = lambda: log["retry_injection_if_pending"].append(1)  # type: ignore
    r._publish_lobby = lambda ctx, demo: log["publish_lobby"].append(1)  # type: ignore
    r._maybe_recommend = lambda ctx: log["maybe_recommend"].append(1)  # type: ignore

    return r, log


# ------------------------------------------------------------------ autouse fixture


@pytest.fixture(autouse=True)
def _patch_rmc():
    """Patch read_match_context at the runtime module level so ChampSelect
    tests never need a real catalog or client. Returns None by default
    (meaning no ctx was read — the publish_lobby / maybe_recommend branches
    are skipped). Individual tests that want a non-None ctx should add their
    own patch on top."""
    with patch(_RMC_PATH, return_value=None):
        yield


# ------------------------------------------------------------------ matrix tests


def test_in_progress_stops_bus_and_starts_poller():
    r, log = _make_runner()
    r._handle_phase("InProgress")
    assert log["stop_event_bus"] and not log["ensure_event_bus"]
    assert log["ensure_live_poller"] and not log["stop_live_poller"]
    assert r.state.snapshot()["lcu"]["phase"] == "InProgress"


def test_in_progress_does_not_clear_post_game():
    r, log = _make_runner()
    r._handle_phase("InProgress")
    assert not log["clear_post_game"]


def test_champ_select_starts_bus_and_clears_post_game():
    r, log = _make_runner()
    r._handle_phase("ChampSelect")
    assert log["ensure_event_bus"]
    assert log["clear_post_game"]
    assert not log["ensure_live_poller"]


def test_champ_select_retries_injection():
    r, log = _make_runner()
    r._handle_phase("ChampSelect")
    assert log["retry_injection_if_pending"]


def test_champ_select_stops_live_poller():
    """_handle_phase always stops the live poller for non-InProgress phases."""
    r, log = _make_runner()
    r._handle_phase("ChampSelect")
    assert log["stop_live_poller"]


def test_lobby_starts_bus_and_resets_draft():
    r, log = _make_runner()
    r._handle_phase("Lobby")
    assert log["ensure_event_bus"]
    assert log["reset_draft_state"]
    assert log["clear_post_game"]
    assert not log["clear_scout"]  # scout not cleared on Lobby


def test_lobby_clears_state_sections_when_not_demo():
    r, log = _make_runner(demo=False)
    r._handle_phase("Lobby")
    snap = r.state.snapshot()
    assert snap["lobby"] is None
    assert snap["draft_intel"] is None
    assert snap["recommendation"] is None


def test_lobby_preserves_state_sections_in_demo_mode():
    r, log = _make_runner(demo=True)
    # pre-set some state
    r.state.set("lobby", {"my_champion": "Lux"})
    r.state.set("draft_intel", {"enemy_comp": "poke"})
    r._handle_phase("Lobby")
    snap = r.state.snapshot()
    # demo=True means the set("lobby", None) branch is skipped
    assert snap["lobby"] == {"my_champion": "Lux"}
    assert snap["draft_intel"] == {"enemy_comp": "poke"}


@pytest.mark.parametrize("phase", ["WaitingForStats", "PreEndOfGame", "EndOfGame"])
def test_post_game_phases_start_bus_and_clear_scout(phase):
    r, log = _make_runner()
    r._handle_phase(phase)
    assert log["ensure_event_bus"]
    assert log["reset_draft_state"]
    assert log["clear_scout"]
    assert not log["clear_post_game"]  # post-game report stays visible


@pytest.mark.parametrize("phase", ["WaitingForStats", "PreEndOfGame", "EndOfGame"])
def test_post_game_phases_clears_state_when_not_demo(phase):
    r, log = _make_runner(demo=False)
    r.state.set("lobby", {"my_champion": "Lux"})
    r._handle_phase(phase)
    snap = r.state.snapshot()
    assert snap["lobby"] is None
    assert snap["recommendation"] is None


@pytest.mark.parametrize("phase", ["Matchmaking", "None"])
def test_idle_phases_stop_bus_and_clear_scout(phase):
    r, log = _make_runner()
    r._handle_phase(phase)
    assert log["stop_event_bus"]
    assert log["reset_draft_state"]
    assert log["clear_scout"]
    assert not log["ensure_event_bus"]


@pytest.mark.parametrize("phase", ["Matchmaking", "None"])
def test_idle_phases_clear_state_when_not_demo(phase):
    r, log = _make_runner(demo=False)
    r.state.set("lobby", {"my_champion": "Lux"})
    r._handle_phase(phase)
    snap = r.state.snapshot()
    assert snap["lobby"] is None
    assert snap["draft_intel"] is None
    assert snap["recommendation"] is None


def test_handle_phase_noop_without_client():
    r, log = _make_runner()
    r.client = None
    r._handle_phase("ChampSelect")
    # Nothing should have fired — guard returns early.
    assert not any(v for v in log.values())
    # Phase should NOT be updated.
    assert r.state.snapshot()["lcu"]["phase"] == "None"


def test_phase_written_to_state():
    for phase in ["InProgress", "ChampSelect", "Lobby", "Matchmaking"]:
        r, _ = _make_runner()
        r._handle_phase(phase)
        assert r.state.snapshot()["lcu"]["phase"] == phase


# ------------------------------------------------------------------ lock test


def test_lock_serializes_concurrent_handle_phase_calls():
    """Two threads both calling _handle_phase must both complete without raising,
    and neither must corrupt the phase string."""
    r, log = _make_runner()

    barrier = threading.Barrier(2, timeout=3)
    errors: list[Exception] = []

    def call(phase: str) -> None:
        try:
            barrier.wait()
            r._handle_phase(phase)
        except Exception as exc:
            errors.append(exc)

    t1 = threading.Thread(target=call, args=("InProgress",))
    t2 = threading.Thread(target=call, args=("ChampSelect",))
    t1.start(); t2.start()
    t1.join(timeout=3); t2.join(timeout=3)

    assert not errors
    # Final phase must be a valid one (whichever ran last).
    assert r.state.snapshot()["lcu"]["phase"] in ("InProgress", "ChampSelect")


def test_lock_does_not_deadlock_on_reentrant_call():
    """_handle_phase uses a non-reentrant lock; if somehow called recursively from
    a stub (shouldn't happen in prod) the second acquire would deadlock. This test
    only confirms non-reentrant calls serialise without deadlock (the lock is not
    held by the test thread)."""
    r, log = _make_runner()
    # Call twice sequentially — should never block.
    done = threading.Event()

    def run():
        r._handle_phase("Lobby")
        r._handle_phase("Matchmaking")
        done.set()

    t = threading.Thread(target=run)
    t.start()
    assert done.wait(timeout=3), "sequential _handle_phase calls deadlocked"
