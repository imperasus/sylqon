"""Offline tests for the draft-intel web port (app/draftintel.py).

The parity tests replay ``fixtures/draft_parity.json`` — ground truth recorded
from the sylqon-side engine by ``python -m sylqon.tools.export_draft_tables``.
Together with the sylqon suite's ``test_draft_tables_export.py`` this proves
engine == port on every fixture input. If a parity test fails here, the port
drifted; fix the port (or regen the artifacts if the sylqon engine changed on
purpose) — never hand-edit the fixture.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from app import draftintel

_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "draft_parity.json").read_text(encoding="utf-8")
)


# -- bundle + lookups ----------------------------------------------------------
def test_bundle_loads_full_roster():
    assert draftintel.patch()
    assert len(draftintel._bundle()["champions"]) >= 160


def test_profiles_carry_derived_threat_flags():
    xerath = draftintel.profile_by_name("Xerath")
    assert "poke" in xerath["threats"]
    leona = draftintel.profile_by_name("leona")  # case-insensitive
    assert "heavy_cc" in leona["threats"]
    assert set(xerath.keys()) == {"name", "tags", "threats", "damage_type"}


def test_profile_by_id_matches_by_name():
    assert draftintel.profile_by_id(266) == draftintel.profile_by_name("Aatrox")
    assert draftintel.profile_by_id("266") == draftintel.profile_by_name("Aatrox")


def test_unknown_lookups_return_none():
    assert draftintel.profile_by_name("Notachamp") is None
    assert draftintel.profile_by_name(None) is None
    assert draftintel.profile_by_name("") is None
    assert draftintel.profile_by_id(999999) is None
    assert draftintel.profile_by_id(None) is None


def test_profiles_are_copies():
    """Callers may mutate returned picks without corrupting the cached bundle."""
    draftintel.profile_by_name("Aatrox")["tags"].append("Mutated")
    assert "Mutated" not in draftintel.profile_by_name("Aatrox")["tags"]


def test_classify_needs_two_picks():
    assert draftintel.classify_comp([])["archetype"] == "unknown"
    assert draftintel.classify_comp([None])["archetype"] == "unknown"
    one = [draftintel.profile_by_name("Aatrox")]
    assert draftintel.classify_comp(one)["archetype"] == "unknown"


# -- parity with the sylqon engine ----------------------------------------------
@pytest.mark.parametrize("case", _FIXTURE["comp_cases"], ids=lambda c: c["id"])
def test_comp_parity(case):
    ally = [draftintel.profile_by_name(n) for n in case["ally"]]
    enemy = [draftintel.profile_by_name(n) for n in case["enemy"]]
    assert all(ally) and all(enemy), "fixture references a champion missing from the bundle"

    expected = case["expected"]
    ally_comp = draftintel.classify_comp(ally)
    enemy_comp = draftintel.classify_comp(enemy)
    assert ally_comp == expected["ally_comp"]
    assert enemy_comp == expected["enemy_comp"]

    ally_summary = draftintel.summarize_team(ally)
    enemy_summary = draftintel.summarize_team(enemy)
    assert ally_summary == expected["ally_summary"]
    assert enemy_summary == expected["enemy_summary"]

    balance = draftintel.draft_balance(ally_comp, enemy_comp,
                                       ally_summary, enemy_summary,
                                       lane_advantage=case["lane_advantage"])
    assert balance == expected["balance"]


@pytest.mark.parametrize("case", _FIXTURE["counter_cases"], ids=lambda c: c["id"])
def test_counter_parity(case):
    assert draftintel.counter_pick_advice(case["ctx"]) == case["expected"]


def test_win_pct_stays_inside_tos_band():
    """The heuristic must never claim a blowout — [35, 65] hard band."""
    for case in _FIXTURE["comp_cases"]:
        assert 35 <= case["expected"]["balance"]["win_pct"] <= 65
