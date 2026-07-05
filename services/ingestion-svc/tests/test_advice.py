"""Offline tests for the advice layer: synthetic timelines with known
deaths/CS/items/wards → expected findings, top-1 selection, HU/EN rendering."""
import pytest

from app.advice import benchmarks, messages
from app.advice.heuristics import (
    Finding,
    PlayerContext,
    cs_benchmark,
    death_context,
    item_timing,
    objective_presence,
    vision,
)
from app.advice.selector import select_top
from app.advice.timeline import TimelineView

TEAM_IDS = {1, 2, 3, 4, 5}
CORE_ITEM = sorted(benchmarks.CORE_ITEM_IDS)[0]
TUN = benchmarks.tuning()


def make_ctx(**overrides) -> PlayerContext:
    defaults = dict(
        participant_id=1,
        team_id=100,
        team_position="TOP",
        champion_name="Garen",
        deaths=0,
        kills=2,
        assists=3,
        wards_placed=8,
        control_wards_bought=2,
    )
    defaults.update(overrides)
    return PlayerContext(**defaults)


def build_view(minutes=30, events=None, cs_per_min=7, gold=500, positions=None):
    """Synthetic Match-V5 timeline: one frame per minute, all 10 participants."""
    events = events or []
    frames = []
    for m in range(minutes + 1):
        frame_events = [e for e in events if m * 60000 <= e.get("timestamp", 0) < (m + 1) * 60000]
        pframes = {}
        for pid in range(1, 11):
            pos = (positions or {}).get(pid, (7000, 7000))
            pframes[str(pid)] = {
                "minionsKilled": int(cs_per_min * m) if pid == 1 else 6 * m,
                "jungleMinionsKilled": 0,
                "currentGold": gold,
                "totalGold": 500 * m,
                "position": {"x": pos[0], "y": pos[1]},
            }
        frames.append({"timestamp": m * 60000, "events": frame_events, "participantFrames": pframes})
    return TimelineView(
        {"frames": frames, "frameInterval": 60000}, participant_id=1, team_participant_ids=TEAM_IDS
    )


def kill_event(ts_min, victim=1, killer=6, assists=(), position=(7000, 7000)):
    return {
        "type": "CHAMPION_KILL",
        "timestamp": int(ts_min * 60000),
        "victimId": victim,
        "killerId": killer,
        "assistingParticipantIds": list(assists),
        "position": {"x": position[0], "y": position[1]},
    }


def ward_event(ts_min, creator=2):
    return {"type": "WARD_PLACED", "timestamp": int(ts_min * 60000),
            "creatorId": creator, "wardType": "YELLOW_TRINKET"}


def monster_kill(ts_min, killer_team=100, killer=2, position=(9800, 4400), assists=()):
    return {
        "type": "ELITE_MONSTER_KILL",
        "timestamp": int(ts_min * 60000),
        "killerTeamId": killer_team,
        "killerId": killer,
        "monsterType": "DRAGON",
        "assistingParticipantIds": list(assists),
        "position": {"x": position[0], "y": position[1]},
    }


def item_event(ts_min, item_id, pid=1):
    return {"type": "ITEM_PURCHASED", "timestamp": int(ts_min * 60000),
            "participantId": pid, "itemId": item_id}


# -- death context ------------------------------------------------------------


def test_death_context_flags_outnumbered_deaths():
    events = [ward_event(m, creator=2) for m in range(1, 30)]  # vision is fine
    events += [kill_event(m, killer=6, assists=(7, 8)) for m in (8, 14, 20, 26)]
    view = build_view(events=events)
    finding = death_context(view, make_ctx(deaths=4), TUN)
    assert finding is not None
    assert finding.message_key == "death_outnumbered"
    assert finding.evidence["outnumbered"] == 4
    assert finding.severity >= 60


def test_death_context_needs_min_deaths():
    events = [kill_event(10, assists=(7, 8))]
    view = build_view(events=events)
    assert death_context(view, make_ctx(deaths=1), TUN) is None


def test_death_context_flags_no_vision():
    # solo kills (no outnumbering) and zero team wards the whole game
    events = [kill_event(m, killer=6, assists=()) for m in (9, 15, 21)]
    view = build_view(events=events)
    finding = death_context(view, make_ctx(deaths=3), TUN)
    assert finding is not None
    assert finding.message_key == "death_no_vision"


def test_death_context_flags_objective_trades():
    events = [ward_event(m, creator=2) for m in range(1, 30)]
    events += [monster_kill(m, killer_team=200, killer=7, position=(9800, 4400)) for m in (10, 16, 22)]
    events += [kill_event(m + 0.2, killer=6, position=(9900, 4500)) for m in (10, 16, 22)]
    view = build_view(events=events)
    finding = death_context(view, make_ctx(deaths=3), TUN)
    assert finding is not None
    assert finding.message_key == "death_objective_trade"


# -- cs benchmark ---------------------------------------------------------------


def test_cs_benchmark_flags_low_farm():
    view = build_view(cs_per_min=3)  # cs@10 = 30 vs TOP bench 62
    finding = cs_benchmark(view, make_ctx(), TUN)
    assert finding is not None
    assert finding.evidence["cs10"] == 30
    assert finding.evidence["bench10"] == 62
    assert finding.severity == 100


def test_cs_benchmark_ok_farm_no_finding():
    view = build_view(cs_per_min=7)  # cs@10 = 70 > 62
    assert cs_benchmark(view, make_ctx(), TUN) is None


def test_cs_benchmark_exempts_support():
    view = build_view(cs_per_min=1)
    assert cs_benchmark(view, make_ctx(team_position="UTILITY"), TUN) is None


# -- item timing -----------------------------------------------------------------


def test_item_timing_flags_late_first_core():
    events = [item_event(22, CORE_ITEM)]
    view = build_view(events=events, gold=400)
    finding = item_timing(view, make_ctx(), TUN)
    assert finding is not None
    assert finding.evidence["first_core_min"] == 22.0
    assert finding.message_key == "item_slow"


def test_item_timing_on_time_no_finding():
    events = [item_event(13, CORE_ITEM), item_event(22, CORE_ITEM)]
    view = build_view(events=events, gold=400)
    assert item_timing(view, make_ctx(), TUN) is None


def test_item_timing_flags_dead_gold():
    events = [item_event(13, CORE_ITEM), item_event(22, CORE_ITEM)]
    view = build_view(events=events, gold=2500)  # sits on 2.5k the whole game
    finding = item_timing(view, make_ctx(), TUN)
    assert finding is not None
    assert finding.evidence["dead_gold_minutes"] >= 3


# -- vision ------------------------------------------------------------------------


def test_vision_flags_wardless_support():
    view = build_view()
    ctx = make_ctx(team_position="UTILITY", wards_placed=6, control_wards_bought=0)
    finding = vision(view, ctx, TUN)  # 0.2/min vs 0.9 bench + 0 control wards
    assert finding is not None
    assert finding.severity >= 60


def test_vision_ok_no_finding():
    view = build_view()
    ctx = make_ctx(team_position="MIDDLE", wards_placed=9, control_wards_bought=1)
    assert vision(view, ctx, TUN) is None


# -- objective presence ---------------------------------------------------------------


def test_objective_presence_flags_absentee():
    far = {1: (1000, 13000)}  # player split-pushing far from every drake
    events = [monster_kill(m, killer=2) for m in (12, 18, 24, 29)]
    view = build_view(events=events, positions=far)
    finding = objective_presence(view, make_ctx(), TUN)
    assert finding is not None
    assert finding.evidence["attended"] == 0
    assert finding.evidence["team_objectives"] == 4


def test_objective_presence_counts_assists_and_proximity():
    near = {1: (9900, 4500)}
    events = [
        monster_kill(12, killer=2, assists=(1,)),
        monster_kill(18, killer=2),  # attended via proximity
    ]
    view = build_view(events=events, positions=near)
    assert objective_presence(view, make_ctx(), TUN) is None


# -- selector + messages -----------------------------------------------------------------


def test_selector_picks_highest_severity():
    a = Finding(type="cs_benchmark", severity=40, message_key="cs_low")
    b = Finding(type="vision", severity=80, message_key="vision_low")
    assert select_top([a, b]) is b


def test_selector_tie_breaks_by_priority():
    a = Finding(type="vision", severity=50, message_key="vision_low")
    b = Finding(type="death_context", severity=50, message_key="death_no_vision")
    assert select_top([a, b]) is b


def test_selector_empty_returns_none():
    assert select_top([]) is None


def test_messages_render_hu_and_en():
    finding = Finding(
        type="cs_benchmark",
        severity=70,
        message_key="cs_low",
        evidence={"cs10": 30, "bench10": 62, "cs15": 50, "bench15": 95, "deficit_pct": 51.6},
    )
    hu = messages.render(finding, "hu", "Garen")
    en = messages.render(finding, "en", "Garen")
    assert "30" in hu and "62" in hu
    assert "30" in en and "62" in en
    assert hu != en


def test_messages_missing_placeholder_falls_back_to_clean():
    finding = Finding(type="cs_benchmark", severity=70, message_key="cs_low", evidence={})
    text = messages.render(finding, "hu", "Garen")
    assert "konzisztencia" in text  # clean_game fallback


def test_messages_none_finding_is_clean_game():
    assert "consistency" in messages.render(None, "en", "Garen")


def test_every_message_key_has_both_languages():
    for key, variants in messages._TEMPLATES.items():
        assert set(variants) == {"hu", "en"}, key
