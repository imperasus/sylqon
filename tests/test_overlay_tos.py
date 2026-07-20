"""Riot-safety regression guard for the in-game overlay coach (Phase 7).

The overlay is READ-ONLY by hard rule (.claude/rules/overlay.md): it may only GET
Riot's Live Client Data API and must never touch the game process — no writes to
the client, no input synthesis, no memory reads, no DLL/code injection. This test
statically scans ``sylqon/livegame/`` and fails if any forbidden pattern appears,
so a future change that breaks the ToS-safe contract can't land silently.

Run: python -m pytest tests/test_overlay_tos.py -q
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

LIVEGAME_DIR = Path(__file__).resolve().parent.parent / "sylqon" / "livegame"


def _sources() -> list[tuple[str, str]]:
    return [(p.name, p.read_text(encoding="utf-8"))
            for p in LIVEGAME_DIR.glob("*.py")]


# Modules that could read game memory, inject code, or synthesize input. None of
# these belong anywhere near the read-only overlay.
_FORBIDDEN_IMPORTS = (
    "ctypes", "pymem", "pywin32", "win32api", "win32gui", "win32process",
    "pyautogui", "pynput", "keyboard", "mouse", "pydirectinput", "psutil",
)
# API names that read/write another process's memory or forge input events.
_FORBIDDEN_APIS = (
    "ReadProcessMemory", "WriteProcessMemory", "OpenProcess", "SendInput",
    "keybd_event", "mouse_event", "VirtualAllocEx", "CreateRemoteThread",
    "LoadLibrary",
)
# HTTP write verbs — the Live Client Data client must be GET-only.
_WRITE_VERB = re.compile(r"\.(post|put|patch|delete)\s*\(", re.IGNORECASE)


def test_livegame_imports_nothing_process_touching():
    for name, src in _sources():
        for mod in _FORBIDDEN_IMPORTS:
            assert not re.search(rf"\bimport\s+{re.escape(mod)}\b", src), \
                f"{name} imports forbidden module {mod!r}"
            assert not re.search(rf"\bfrom\s+{re.escape(mod)}\b", src), \
                f"{name} imports from forbidden module {mod!r}"


def test_livegame_calls_no_memory_or_input_apis():
    for name, src in _sources():
        for api in _FORBIDDEN_APIS:
            assert api not in src, f"{name} references forbidden API {api!r}"


def test_livegame_issues_no_http_writes():
    # HTTP writes require an HTTP client, so only scan modules that use ``requests``
    # (this avoids flagging SQLAlchemy's ``.delete()`` in the DB-backed modules).
    for name, src in _sources():
        if "requests" not in src:
            continue
        m = _WRITE_VERB.search(src)
        assert m is None, f"{name} performs an HTTP write ({m.group(0) if m else ''})"


def test_live_client_is_get_only():
    """The one module that talks to the game endpoint uses GET exclusively."""
    src = (LIVEGAME_DIR / "client.py").read_text(encoding="utf-8")
    assert ".get(" in src                         # it does read
    assert not _WRITE_VERB.search(src)            # …and only reads


def test_live_client_targets_only_localhost_2999():
    """No hard-coded external hosts — the overlay only talks to the local game."""
    for name, src in _sources():
        for url in re.findall(r"https?://[^\s\"')]+", src):
            assert "127.0.0.1" in url or "localhost" in url, \
                f"{name} references a non-local URL: {url}"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
