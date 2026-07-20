"""F4a — team power-curve (tempo vs scaling) read."""
from __future__ import annotations

from sylqon.analysis import power_curve


def _p(name, *tags):
    return {"name": name, "tags": list(tags)}


def test_curve_normalized():
    c = power_curve.champion_curve("Jinx", {"Marksman"})
    assert abs(sum(c.values()) - 1.0) < 1e-9


def test_marksman_scales_late():
    c = power_curve.champion_curve("Jinx", {"Marksman"})
    assert c["late"] > c["early"]


def test_hard_late_override_pushes_late():
    base = power_curve.champion_curve("Sett", {"Fighter"})       # class prior
    late = power_curve.champion_curve("Kassadin", {"Assassin"})  # hard-late outlier
    assert late["late"] > base["late"]


def test_hard_early_override_pushes_early():
    c = power_curve.champion_curve("Draven", {"Marksman"})
    # A hard-early marksman should read earlier than a vanilla one.
    vanilla = power_curve.champion_curve("Jinx", {"Marksman"})
    assert c["early"] > vanilla["early"]


def test_tempo_read_detects_out_scaling():
    ally = [_p("Jinx", "Marksman"), _p("Kayle", "Fighter"), _p("Kassadin", "Assassin")]
    enemy = [_p("Draven", "Marksman"), _p("Renekton", "Fighter"), _p("Pantheon", "Fighter")]
    read = power_curve.tempo_read(ally, enemy)
    assert read["sign"] == 1
    assert read["phase"] == "late"
    assert "out-scale" in read["label"].lower()


def test_tempo_read_detects_out_tempo():
    ally = [_p("Draven", "Marksman"), _p("Renekton", "Fighter"), _p("Pantheon", "Fighter")]
    enemy = [_p("Jinx", "Marksman"), _p("Kayle", "Fighter"), _p("Kassadin", "Assassin")]
    read = power_curve.tempo_read(ally, enemy)
    assert read["sign"] == -1
    assert read["phase"] == "early"


def test_tempo_read_even_curves():
    team = [_p("Ahri", "Mage"), _p("Vi", "Fighter")]
    read = power_curve.tempo_read(team, list(team))
    assert read["sign"] == 0
    assert read["phase"] == "mid"


def test_empty_team_is_neutral():
    c = power_curve.team_curve([])
    assert abs(c["early"] - 1 / 3) < 1e-9
