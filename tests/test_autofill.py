"""Offline tests for the off-role ("autofill") read (lcu/scout.autofill_read).

An autofilled laner is one of the most exploitable pre-game signals there is, so
the call has to be right: only fire when the assigned role genuinely isn't what
they play, and stay silent when the history is too thin to know.

Run: python -m pytest tests/test_autofill.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon.lcu.scout import autofill_read


def test_main_role_is_never_autofill():
    roles = {"middle": 18, "top": 2}
    assert autofill_read(roles, "middle") is None


def test_off_role_with_almost_no_history_is_flagged():
    roles = {"middle": 18, "utility": 2}
    read = autofill_read(roles, "utility")
    assert read is not None
    assert read["main_role"] == "middle"
    assert read["games"] == 2
    assert read["share"] == 0.1


def test_secondary_role_played_often_is_not_autofill():
    """A comfortable two-role player isn't autofilled — 40% is a real pool."""
    roles = {"middle": 12, "top": 8}
    assert autofill_read(roles, "top") is None


def test_role_never_played_is_flagged():
    roles = {"bottom": 20}
    read = autofill_read(roles, "jungle")
    assert read is not None
    assert read["games"] == 0
    assert read["share"] == 0.0


def test_thin_history_stays_silent():
    """Below the minimum sample we cannot tell autofill from a small pool."""
    assert autofill_read({"middle": 3, "top": 1}, "top") is None


def test_missing_inputs_are_safe():
    assert autofill_read(None, "top") is None
    assert autofill_read({}, "top") is None
    assert autofill_read({"middle": 20}, "") is None


def test_boundary_share_is_not_autofill():
    """Exactly at the share threshold counts as a played role, not a fill."""
    roles = {"middle": 15, "top": 5}   # top = 25%
    assert autofill_read(roles, "top") is None


def test_just_below_boundary_is_autofill():
    roles = {"middle": 16, "top": 4}   # top = 20%
    assert autofill_read(roles, "top") is not None


def test_main_role_tie_is_resolved_deterministically():
    """Ties must not make the read flap between polls."""
    roles = {"middle": 10, "top": 10}
    first = autofill_read(roles, "utility")
    assert first == autofill_read(dict(reversed(list(roles.items()))), "utility")
