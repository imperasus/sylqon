"""Property/invariant tests for the deterministic loadout pipeline.

Whatever the matchup, the compiled loadout the injector receives must always be
LEGAL: right length, resolvable non-duplicate item ids, a valid rune block, an
in-row shard trio, legal summoners, and counter coverage that never regresses
below the meta baseline. These invariants hold across every archetype × comp in
the golden matrix (reused here) plus edge cases.

Fully offline — synthetic builds, no AI/LCU/network.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon.analysis import lane_counter
from sylqon.data import static
from test_golden_loadouts import BUILDS, ENEMY_COMPS, SCENARIOS, _compile, _ctx

ALL_SCENARIOS = SCENARIOS + [
    # extra edge cases: hidden enemies, single mixed threat, everything-at-once
    ("adc", "bottom", "Jinx", "balanced"),
    ("mage", "middle", "Syndra", "balanced"),
    ("bruiser", "top", "Darius", "balanced"),
]


def _compiled():
    return [(_compile(bk, role, champ, ck), bk, role, champ, ck)
            for bk, role, champ, ck in ALL_SCENARIOS]


class TestLegalItems:
    def test_item_count_matches_candidate(self):
        for lo, bk, role, champ, ck in _compiled():
            expected = len(BUILDS[bk]()["items"])
            assert len(lo.items) == expected, (bk, ck)

    def test_no_duplicate_items(self):
        for lo, *_ in _compiled():
            ids = [i["id"] for i in lo.items]
            assert len(ids) == len(set(ids)), ids

    def test_item_ids_are_positive_ints(self):
        for lo, *_ in _compiled():
            for i in lo.items:
                assert isinstance(i["id"], int) and i["id"] > 0

    def test_boots_first(self):
        for lo, *_ in _compiled():
            assert lo.items[0]["id"] == lo.boots["id"]


class TestLegalRunes:
    def test_valid_rune_block(self):
        from sylqon.loadout import _valid_rune_block
        for lo, *_ in _compiled():
            ids = lo.rune_perk_ids
            keystone = static.RUNE_BY_ID.get(ids[0])
            primary = [static.RUNE_BY_ID.get(i) for i in ids[1:4]]
            secondary = [static.RUNE_BY_ID.get(i) for i in ids[4:6]]
            sec_style = static.STYLE_BY_ID.get(lo.secondary_style_id)
            assert _valid_rune_block(keystone, primary, secondary, sec_style)

    def test_primary_style_matches_keystone(self):
        for lo, *_ in _compiled():
            keystone = static.RUNE_BY_ID.get(lo.rune_perk_ids[0])
            assert static.RUNE_STYLES[static.KEYSTONE_STYLE[keystone]] == lo.primary_style_id


class TestLegalShardsAndSpells:
    def test_three_shards_in_rows(self):
        rows = [static.SHARD_ROW_OFFENSE, static.SHARD_ROW_FLEX, static.SHARD_ROW_DEFENSE]
        for lo, *_ in _compiled():
            names = [static.SHARD_BY_ID.get(s) for s in lo.shard_ids]
            assert len(names) == 3
            for i, n in enumerate(names):
                assert n in rows[i], (n, i)

    def test_spells_legal_and_distinct(self):
        for lo, bk, role, champ, ck in _compiled():
            if role == "jungle":
                assert lo.spell1 == "Smite"
            else:
                assert lo.spell1 in static.ALLOWED_SPELL1
            assert lo.spell2 in static.ALLOWED_SPELL2
            assert lo.spell1 != lo.spell2


class TestCounterCoverageMonotonic:
    def _covered(self, items, reqs):
        covered = 0
        for accepted, _ in reqs:
            if any(set(static.ITEM_COUNTER_TAGS.get(i.get("id", 0), ())) & accepted
                   for i in items):
                covered += 1
        return covered

    def test_enforcement_never_reduces_coverage(self):
        """The final build covers at least as many mandated requirement sets as
        the meta baseline did — enforcement only ever adds coverage."""
        import sylqon.loadout as loadout_mod
        from test_golden_loadouts import _StubCatalog
        for bk, role, champ, ck in ALL_SCENARIOS:
            ctx = _ctx(champ, role, ENEMY_COMPS[ck])
            reqs = lane_counter.combined_requirements(ctx)
            if not reqs:
                continue
            candidate = BUILDS[bk]()
            base = loadout_mod.from_candidate(candidate, ctx, "seed")
            meta_cov = self._covered(base.items, reqs)
            final = loadout_mod.apply_ai_decision(base, None, ctx, _StubCatalog(), candidate)
            final_cov = self._covered(final.items, reqs)
            assert final_cov >= meta_cov, (bk, ck, meta_cov, final_cov)


class TestDeterminism:
    def test_same_inputs_same_output(self):
        for bk, role, champ, ck in ALL_SCENARIOS:
            a = _compile(bk, role, champ, ck)
            b = _compile(bk, role, champ, ck)
            assert [i["id"] for i in a.items] == [i["id"] for i in b.items]
            assert a.rune_perk_ids == b.rune_perk_ids
            assert a.shard_ids == b.shard_ids
            assert (a.spell1, a.spell2) == (b.spell1, b.spell2)


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
