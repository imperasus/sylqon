"""Offline tests for the kill-pressure Ignite branch in
loadout.deterministic_spells and the rune_page_options / spell_combo_options
payload plumbing in cache/opgg.py.

Run: python -m pytest tests/test_kill_pressure_spells.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon import loadout as loadout_mod
from sylqon.cache import opgg
from sylqon.lcu.lobby import EnemyProfile, MatchContext


def _ctx(enemies=None, champion="Darius", role="top") -> MatchContext:
    return MatchContext(
        summoner_id=1, my_champion=champion, my_champion_id=1, my_role=role,
        locked=True, all_locked=True, my_turn=False, enemies=enemies or [],
        allies=[], fingerprint="fp",
    )


def _enemy(name, role="top", **kw) -> EnemyProfile:
    defaults = dict(champion_id=1, role=role, side="enemy",
                    damage_type="AD", tags=[], threats=[])
    defaults.update(kw)
    return EnemyProfile(name=name, **defaults)


def _build(spell1="Teleport", spell2="Flash", options=("Teleport", "Flash", "Ignite")):
    return {"spell1": spell1, "spell2": spell2, "spell_options": list(options)}


class TestKillPressureIgnite:
    def test_winnable_lane_takes_ignite(self):
        # Darius top into a squishy killable laner, op.gg runs Ignite → Ignite.
        ctx = _ctx([_enemy("Riven")], champion="Darius", role="top")
        s1, _ = loadout_mod.deterministic_spells(_build(), ctx)
        assert s1 == "Ignite"

    def test_tank_lane_keeps_teleport(self):
        # Into Ornn (unkillable) the dive summoner is wrong → keep TP.
        ctx = _ctx([_enemy("Ornn", threats=["tank"])], champion="Darius", role="top")
        s1, _ = loadout_mod.deterministic_spells(_build(), ctx)
        assert s1 == "Teleport"

    def test_sustain_lane_keeps_teleport(self):
        ctx = _ctx([_enemy("Aatrox", threats=["heavy_healing"])],
                   champion="Darius", role="top")
        s1, _ = loadout_mod.deterministic_spells(_build(), ctx)
        assert s1 == "Teleport"

    def test_non_kill_champion_keeps_default(self):
        # Malphite is not a kill-pressure laner → keep the op.gg default.
        ctx = _ctx([_enemy("Riven")], champion="Malphite", role="top")
        s1, _ = loadout_mod.deterministic_spells(
            _build(spell1="Teleport"), ctx)
        assert s1 == "Teleport"

    def test_ignite_not_observed_keeps_default(self):
        ctx = _ctx([_enemy("Riven")], champion="Darius", role="top")
        s1, _ = loadout_mod.deterministic_spells(
            _build(options=("Teleport", "Flash")), ctx)
        assert s1 == "Teleport"

    def test_hidden_lane_keeps_default(self):
        # No same-role opponent (blind pick) → keep the safe default.
        ctx = _ctx([_enemy("Ahri", role="middle")], champion="Darius", role="top")
        s1, _ = loadout_mod.deterministic_spells(_build(), ctx)
        assert s1 == "Teleport"

    def test_defensive_branch_wins_over_kill_pressure(self):
        # Mid burst laner (kill champ) but 3+ heavy CC → Cleanse takes priority.
        ctx = _ctx([_enemy(n, role="middle", threats=["heavy_cc"])
                    for n in ("Leona", "Lissandra", "Amumu")]
                   + [_enemy("Ahri", role="middle")],
                   champion="Zed", role="middle")
        build = _build(spell1="Ignite",
                       options=("Ignite", "Flash", "Cleanse"))
        s1, _ = loadout_mod.deterministic_spells(build, ctx)
        assert s1 == "Cleanse"


class TestPayloadPlumbing:
    def _payload(self):
        # Two rune pages + two spell combos with sample counts.
        return {
            "role": "middle",
            "rune_page_options": [
                {"primary_page_id": 8100, "primary_rune_ids": [8112, 8126, 8120, 8106],
                 "secondary_page_id": 8200, "secondary_rune_ids": [8226, 8210],
                 "stat_mod_ids": [5008, 5008, 5011], "play": 1000, "win": 520},
                {"primary_page_id": 8100, "primary_rune_ids": [8112, 8126, 8120, 8106],
                 "secondary_page_id": 8400, "secondary_rune_ids": [8224, 8473],
                 "stat_mod_ids": [5008, 5008, 5011], "play": 300, "win": 156},
            ],
            "summoner_spell_combos": [
                {"ids": [4, 14], "play": 900, "win": 470},   # Flash + Ignite
                {"ids": [4, 21], "play": 200, "win": 96},    # Flash + Barrier
            ],
        }

    def test_rune_page_options_resolved(self):
        opts = opgg._rune_page_options(self._payload())
        assert len(opts) == 2
        assert opts[0]["keystone"] == "Electrocute"
        assert opts[1]["secondary_style"] == "Resolve"
        assert opts[1]["secondary_runes"] == ["Nullifying Orb", "Bone Plating"]
        assert opts[0]["games"] == 1000 and opts[0]["win_rate"] == 0.52

    def test_unresolvable_page_dropped(self):
        payload = {"rune_page_options": [
            {"primary_rune_ids": [999999, 1, 2, 3],  # bad keystone id
             "secondary_page_id": 8200, "secondary_rune_ids": [8226, 8210],
             "stat_mod_ids": [5008, 5008, 5011], "play": 100, "win": 50},
        ]}
        assert opgg._rune_page_options(payload) == []

    def test_spell_combo_options_slotted(self):
        combos = opgg._spell_combo_options(self._payload(), "middle")
        assert combos[0]["spell1"] == "Ignite" and combos[0]["spell2"] == "Flash"
        assert combos[0]["games"] == 900 and combos[0]["win_rate"] == round(470 / 900, 3)

    def test_absent_keys_empty(self):
        assert opgg._rune_page_options({}) == []
        assert opgg._spell_combo_options({}, "top") == []


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
