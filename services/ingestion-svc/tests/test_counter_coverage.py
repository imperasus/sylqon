"""Offline tests for the counter-item coverage heuristic (the post-game half of
the draft loadout coach's closed loop): a healing/tank enemy comp the player
failed to itemise against surfaces as advice.

Reuses the synthetic-timeline helpers from test_advice.
"""
from __future__ import annotations

from app.advice import benchmarks, messages
from app.advice.counters import counter_item_coverage
from app.advice.selector import select_top

from tests.test_advice import build_view, item_event, make_ctx

TUN = benchmarks.tuning()

ANTI_HEAL = 3033      # Mortal Reminder
PERCENT_PEN = 3036    # Lord Dominik's Regards
PLAIN_DMG = 3031      # Infinity Edge (no counter tag)


def _ctx(enemies, role="BOTTOM"):
    return make_ctx(team_position=role, champion_name="Jinx",
                    enemy_champions=tuple(enemies))


class TestAntiHeal:
    def test_missing_antiheal_vs_two_healers_flags(self):
        view = build_view(minutes=28, events=[item_event(14, PLAIN_DMG)])
        f = counter_item_coverage(view, _ctx(["Soraka", "Aatrox", "Ahri"]), TUN)
        assert f is not None and f.message_key == "counter_no_antiheal"
        assert f.evidence["healers"] == 2

    def test_antiheal_bought_no_finding(self):
        view = build_view(minutes=28, events=[item_event(16, ANTI_HEAL)])
        assert counter_item_coverage(view, _ctx(["Soraka", "Vladimir"]), TUN) is None

    def test_single_healer_no_finding(self):
        view = build_view(minutes=28, events=[item_event(14, PLAIN_DMG)])
        assert counter_item_coverage(view, _ctx(["Soraka", "Ahri"]), TUN) is None


class TestPercentPen:
    def test_missing_pen_vs_two_tanks_flags(self):
        view = build_view(minutes=28, events=[item_event(14, PLAIN_DMG)])
        f = counter_item_coverage(view, _ctx(["Ornn", "Sion", "Ahri"]), TUN)
        assert f is not None and f.message_key == "counter_no_pen"
        assert f.evidence["tanks"] == 2

    def test_pen_bought_no_finding(self):
        view = build_view(minutes=28, events=[item_event(20, PERCENT_PEN)])
        assert counter_item_coverage(view, _ctx(["Ornn", "Sion"]), TUN) is None

    def test_antiheal_takes_priority_over_pen(self):
        # Comp has both 2 healers and 2 tanks, no counters bought → anti-heal wins.
        view = build_view(minutes=28, events=[item_event(14, PLAIN_DMG)])
        f = counter_item_coverage(
            view, _ctx(["Soraka", "Aatrox", "Ornn", "Sion"]), TUN)
        assert f.message_key == "counter_no_antiheal"


class TestGating:
    def test_short_game_exempt(self):
        # Under counter_min_game_min there hasn't been time to complete a counter.
        view = build_view(minutes=15, events=[item_event(14, PLAIN_DMG)])
        assert counter_item_coverage(view, _ctx(["Soraka", "Aatrox"]), TUN) is None

    def test_support_role_exempt(self):
        view = build_view(minutes=28, events=[item_event(14, PLAIN_DMG)])
        assert counter_item_coverage(
            view, _ctx(["Soraka", "Aatrox"], role="UTILITY"), TUN) is None

    def test_no_enemies_no_finding(self):
        view = build_view(minutes=28, events=[item_event(14, PLAIN_DMG)])
        assert counter_item_coverage(view, _ctx([]), TUN) is None


class TestRenderingAndSelection:
    def test_messages_render_both_langs(self):
        view = build_view(minutes=28, events=[item_event(14, PLAIN_DMG)])
        f = counter_item_coverage(view, _ctx(["Soraka", "Aatrox"]), TUN)
        hu = messages.render(f, "hu", "Jinx")
        en = messages.render(f, "en", "Jinx")
        assert "anti-heal" in en and "Jinx" not in hu[:0]  # both non-empty, formatted
        assert "Grievous" in en

    def test_selector_ranks_counter_finding(self):
        view = build_view(minutes=28, events=[item_event(14, PLAIN_DMG)])
        f = counter_item_coverage(view, _ctx(["Soraka", "Aatrox"]), TUN)
        assert select_top([f]).type == "counter_coverage"
