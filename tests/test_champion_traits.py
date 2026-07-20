"""F0 — full-roster champion-trait coverage guards.

The curated threat tables in ``data/static`` historically covered only a slice
of the roster, silently leaving most champions as a "neutral blob" the draft
engine could not read. ``scripts/generate_champion_traits.py`` derives the
deterministically-knowable traits for the WHOLE roster and ``static`` unions
them into the curated sets (curated always wins). These tests enforce that
completeness as an invariant and pin the union semantics so a regenerate can
widen coverage but never silently drop curated knowledge.

Offline: everything asserts against the committed ``generated_champion_traits.json``
(the generator's output), never the network.
"""
from __future__ import annotations

import json
from pathlib import Path

from sylqon.data import static

GENERATED = json.loads(
    (Path(static.__file__).with_name("generated_champion_traits.json"))
    .read_text(encoding="utf-8"))

# The live roster is ~170 champions; keep a generous floor so the test is robust
# to a champion release/removal but still catches a truncated/empty generation.
ROSTER_FLOOR = 165


# -- generated-file integrity ------------------------------------------------
def test_generated_file_shape():
    assert GENERATED.get("_patch"), "generated traits missing a _patch stamp"
    assert len(GENERATED["damage_type"]) >= ROSTER_FLOOR
    assert set(GENERATED["damage_type"].values()) <= {"ad", "ap", "mixed"}


# -- damage_type: whole-roster coverage, curated wins ------------------------
def test_damage_type_covers_full_roster():
    # Every champion the generator saw has a concrete damage type in the merged
    # map — no champion falls through to an implicit default silently.
    for name in GENERATED["damage_type"]:
        assert name in static.CHAMPION_DAMAGE_TYPE
        assert static.CHAMPION_DAMAGE_TYPE[name] in {"ad", "ap", "mixed"}
    assert len(static.CHAMPION_DAMAGE_TYPE) >= ROSTER_FLOOR


def test_curated_damage_type_overrides_generated():
    # Where the hand table and the generator disagree, the hand call must win.
    # Qiyana reads AP by info scores but builds lethality AD; Jax is deliberately
    # "mixed" (universal counter items) though info scores lean AD.
    assert static.CHAMPION_DAMAGE_TYPE["Qiyana"] == "ad"
    assert static.CHAMPION_DAMAGE_TYPE["Jax"] == "mixed"
    assert GENERATED["damage_type"].get("Qiyana") == "ap"  # generator's raw read


# -- threat sets: union invariant (curated ⊆ merged) -------------------------
def test_merged_threat_sets_are_supersets_of_curated():
    # The merge must only ever WIDEN. If a future regeneration drops a curated
    # member this fails loudly.
    def gen(tag):
        return {n for n, t in GENERATED["threats"].items() if tag in t}

    assert gen("heavy_cc") | static.HEAVY_CC_CHAMPS == static.HEAVY_CC_CHAMPS
    assert gen("heavy_healing") | static.HEAVY_HEALING == static.HEAVY_HEALING
    assert gen("tank") | static.HEAVY_TANK == static.HEAVY_TANK
    assert gen("suppression") | static.SUPPRESSION_CHAMPS == static.SUPPRESSION_CHAMPS


def test_coverage_actually_widened():
    # Guard the whole point of F0: the merged sets are materially larger than the
    # old curated-only slice, i.e. most of the roster is now readable.
    assert len(static.HEAVY_CC_CHAMPS) >= 80
    assert len(static.HEAVY_HEALING) >= 40
    assert len(static.HEAVY_TANK) >= 40


def test_threat_sets_not_degenerate():
    # A keyword-scan blowup would tag nearly everyone; hard CC is common but not
    # universal. Bound it so an over-broad regex is caught.
    assert len(static.HEAVY_CC_CHAMPS) <= 130


# -- regression anchors: specific, checkable classifications -----------------
def test_known_threat_assignments():
    assert "Leona" in static.HEAVY_CC_CHAMPS
    assert "Soraka" in static.HEAVY_HEALING
    assert "Malphite" in static.HEAVY_TANK
    assert "Malzahar" in static.SUPPRESSION_CHAMPS
    assert "Ambessa" in static.SUPPRESSION_CHAMPS  # R "suppresses ... then stuns"


def test_deliberate_suppression_exclusions_hold():
    # The curated set deliberately excludes these (not QSS-relevant suppressions);
    # the union must not re-introduce them via a loose keyword match.
    assert "Tahm Kench" not in static.SUPPRESSION_CHAMPS
    assert "Mordekaiser" not in static.SUPPRESSION_CHAMPS
