"""Offline drift-guards for the ingestion-svc draft-intel bundle + fixture.

The hosted service ports the draft engine without importing ``sylqon``; the
bridge is the generated ``draft_tables.json`` bundle and the
``draft_parity.json`` fixture (see ``sylqon/tools/export_draft_tables.py``).
These tests fail whenever the sylqon-side source of truth (threat tables in
``data/static.py``, the engine in ``analysis/draft_intel.py`` or the team
summary in ``lcu/lobby.py``) drifts from the committed artifacts — the fix is
always a regen, never a hand-edit:

    python -m sylqon.tools.export_draft_tables

Run: python -m pytest tests/test_draft_tables_export.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon.analysis.draft_intel import counter_pick_advice
from sylqon.data import static
from sylqon.lcu.lobby import _threats
from sylqon.tools.export_draft_tables import (
    BUNDLE_PATH,
    COMP_CASES,
    COUNTER_CASES,
    FIXTURE_PATH,
    _ctx_namespace,
    run_comp_case,
)

REGEN = "regen with: python -m sylqon.tools.export_draft_tables"


def _load(path: Path) -> dict:
    assert path.exists(), f"missing committed artifact {path} — {REGEN}"
    return json.loads(path.read_text(encoding="utf-8"))


def test_bundle_threat_tables_in_sync():
    bundle = _load(BUNDLE_PATH)
    assert bundle["heavy_poke"] == sorted(static.HEAVY_POKE), REGEN
    assert bundle["split_push"] == sorted(static.SPLIT_PUSH_CHAMPS), REGEN
    assert len(bundle["champions"]) >= 160
    for key, prof in bundle["champions"].items():
        assert prof["threats"] == _threats(prof["name"]), \
            f"threats drifted for {prof['name']} (key {key}) — {REGEN}"
        assert prof["damage_type"] in {"AD", "AP", "Mixed"}


def test_fixture_cases_match_tool_definitions():
    """Editing COMP_CASES/COUNTER_CASES without a regen must fail loudly."""
    fixture = _load(FIXTURE_PATH)
    assert [c["id"] for c in fixture["comp_cases"]] == [c[0] for c in COMP_CASES], REGEN
    assert [c["id"] for c in fixture["counter_cases"]] == [c[0] for c in COUNTER_CASES], REGEN


def test_fixture_matches_source_engine():
    """The committed ground truth must equal what the sylqon engine produces
    today for the same bundle-derived inputs — the sylqon half of the parity
    contract (the service half lives in ingestion-svc tests)."""
    bundle = _load(BUNDLE_PATH)
    fixture = _load(FIXTURE_PATH)
    for case in fixture["comp_cases"]:
        actual = run_comp_case(bundle, case["ally"], case["enemy"],
                               case["lane_advantage"])
        assert actual == case["expected"], f"comp case {case['id']!r} drifted — {REGEN}"
    for case in fixture["counter_cases"]:
        actual = counter_pick_advice(_ctx_namespace(case["ctx"]))
        assert actual == case["expected"], f"counter case {case['id']!r} drifted — {REGEN}"
