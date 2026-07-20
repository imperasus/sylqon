"""State-reactive coaching triggers (overlay coach, Phase 3).

Where a `Mission` measures a delta over a window, a *trigger* fires the instant
the live snapshot crosses a coaching-relevant edge — an ultimate unlocking, an
item completing, the enemy laner dying, gold worth backing for, an objective
about to spawn, or your health dropping into retreat range. Each emitted `Alert`
carries a one-line call **and its rationale** (the "why"), so the coach teaches a
pattern instead of barking an order.

Everything here is derived from the read-only Live Client Data snapshot
(`LiveGameState`) — the same on-screen information the player already has. The
engine is edge-triggered off the previous snapshot and rate-limited per category
so a busy teamfight never spams the overlay.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from sylqon.livegame.state import LiveGameState

# -- categories --------------------------------------------------------------
ULT_SPIKE = "ult_spike"
ITEM_SPIKE = "item_spike"
ENEMY_DOWN = "enemy_down"
RECALL_GOLD = "recall_gold"
OBJECTIVE_SETUP = "objective_setup"
LOW_HP = "low_hp"
DEATH_REVIEW = "death_review"
MATCHUP_PLAN = "matchup_plan"

# Per-category cooldown in *game seconds* — the minimum gap between two alerts of
# the same kind, so a fluctuating stat (HP in a fight) can't machine-gun the UI.
_COOLDOWN = {
    ULT_SPIKE: 40.0,
    ITEM_SPIKE: 30.0,
    ENEMY_DOWN: 35.0,
    RECALL_GOLD: 60.0,
    OBJECTIVE_SETUP: 90.0,
    LOW_HP: 25.0,
    DEATH_REVIEW: 20.0,
    MATCHUP_PLAN: 1e9,      # once per game (reset clears it for the next game)
}

# Higher = more urgent. Safety (retreat) outranks opportunity; opportunity
# outranks tempo/econ nudges. The UI shows the top alert; voice speaks it.
_PRIORITY = {
    LOW_HP: 100,
    DEATH_REVIEW: 80,
    ENEMY_DOWN: 70,
    OBJECTIVE_SETUP: 65,
    ULT_SPIKE: 60,
    ITEM_SPIKE: 55,
    MATCHUP_PLAN: 50,
    RECALL_GOLD: 40,
}

# -- tuning knobs (module-level; Phase 7 can lift these into config) ----------
_ENEMY_DOWN_MIN = 10.0      # only flag an enemy death worth ≥10s of map pressure
_RECALL_GOLD_MIN = 1300.0   # gold worth backing for (a legendary component tier)
_RECALL_REARM_GOLD = 400.0  # once gold falls below this we assume a back happened
_DRAGON_WINDOW = 45.0       # "spawning soon" lead time for a dragon
_BARON_WINDOW = 60.0        # …and for baron (bigger setup)
_BARON_FIRST = 1200.0       # baron first spawns at 20:00
_LOW_HP_PCT = 25.0          # retreat threshold

_ULT_MILESTONE = {1: 6, 2: 11, 3: 16}   # ult level → champion level it unlocks at
_MATCHUP_WINDOW = 120.0                  # only pitch the lane plan in the first 2 min
_MAX_ALERTS = 2                          # never surface more than this per tick


@dataclass(frozen=True)
class Alert:
    id: str
    category: str
    text: str          # the imperative call (≤ ~1 short line)
    rationale: str     # the "why" — the coaching pattern behind the call
    tone: str          # good | bad | info
    priority: int

    def to_dict(self) -> dict:
        return asdict(self)


def _my_completed(live: LiveGameState) -> int:
    """My own completed-item count from the roster (by name), 0 if not found."""
    for p in live.roster or []:
        if p.get("side") == "ally" and p.get("name") == live.my_name:
            return int(p.get("completed_items") or 0)
    return 0


def _enemy_laner(live: LiveGameState) -> dict | None:
    if not live.role:
        return None
    return next((p for p in (live.roster or [])
                 if p.get("side") == "enemy" and p.get("role") == live.role), None)


class TriggerEngine:
    """Edge-triggered, rate-limited coaching alerts off the live snapshot."""

    def __init__(self) -> None:
        self._prev: LiveGameState | None = None
        self._last_fired: dict[str, float] = {}
        self._recall_armed: bool = True   # re-armed after each back
        self._last_time: float = 0.0

    def reset(self) -> None:
        self._prev = None
        self._last_fired = {}
        self._recall_armed = True
        self._last_time = 0.0

    def evaluate(self, live: LiveGameState) -> list[dict]:
        """Return the top alerts (≤ _MAX_ALERTS) for this tick, as plain dicts.
        Pure w.r.t. the game client; only mutates the engine's own cooldown state."""
        if not live.active or live.game_time <= 0:
            self.reset()
            return []
        # A restarted clock => new game: drop all edge/cooldown state.
        if live.game_time + 2.0 < self._last_time:
            self.reset()
        self._last_time = live.game_time

        prev = self._prev
        self._prev = live
        if prev is None:
            return []  # first tick only primes the baseline — no burst on mount

        candidates = [a for a in self._detect(prev, live) if self._ready(a, live)]
        candidates.sort(key=lambda a: a.priority, reverse=True)
        chosen = candidates[:_MAX_ALERTS]
        for a in chosen:
            self._last_fired[a.category] = live.game_time
        return [a.to_dict() for a in chosen]

    # -- internals -----------------------------------------------------------
    def _ready(self, alert: Alert, live: LiveGameState) -> bool:
        last = self._last_fired.get(alert.category)
        return last is None or (live.game_time - last) >= _COOLDOWN[alert.category]

    def _detect(self, prev: LiveGameState, live: LiveGameState) -> list[Alert]:
        out: list[Alert] = []
        self._ult(prev, live, out)
        self._item(prev, live, out)
        self._enemy_down(prev, live, out)
        self._recall(prev, live, out)
        self._objective(prev, live, out)
        self._low_hp(prev, live, out)
        self._death_review(prev, live, out)
        self._matchup(prev, live, out)
        return out

    def _ult(self, prev, live, out) -> None:
        before = int((prev.abilities or {}).get("ult_level") or 0)
        now = int((live.abilities or {}).get("ult_level") or 0)
        if now > before and now in _ULT_MILESTONE:
            lvl = _ULT_MILESTONE[now]
            out.append(Alert(
                id=f"ult-{now}", category=ULT_SPIKE,
                text=f"Ultimate up (level {lvl}) — look for a fight",
                rationale="Hitting an ult breakpoint is a power spike; press it "
                          "before the enemy matches it.",
                tone="good", priority=_PRIORITY[ULT_SPIKE]))

    def _item(self, prev, live, out) -> None:
        before, now = _my_completed(prev), _my_completed(live)
        if now > before and now > 0:
            out.append(Alert(
                id=f"item-{now}", category=ITEM_SPIKE,
                text="Item complete — force a play while it's live",
                rationale="A finished legendary is a ~20-30s power window; convert "
                          "it into a fight, dive or objective before it's the norm.",
                tone="good", priority=_PRIORITY[ITEM_SPIKE]))

    def _enemy_down(self, prev, live, out) -> None:
        e_now = _enemy_laner(live)
        e_prev = _enemy_laner(prev)
        if not e_now or not e_prev:
            return
        timer = float(e_now.get("respawn_timer") or 0.0)
        was_dead = bool(e_prev.get("is_dead"))
        if bool(e_now.get("is_dead")) and not was_dead and timer >= _ENEMY_DOWN_MIN:
            role = (live.role or "lane").title()
            out.append(Alert(
                id="enemy-down", category=ENEMY_DOWN,
                text=f"Enemy {role} dead ~{int(timer)}s — take plates or cross-map",
                rationale="A dead laner can't answer; trade the free lane time for "
                          "turret plates, vision, or a play elsewhere.",
                tone="good", priority=_PRIORITY[ENEMY_DOWN]))

    def _recall(self, prev, live, out) -> None:
        gold = float(live.current_gold or 0.0)
        # Re-arm once we've clearly spent (a back happened); fire on the way up.
        if gold < _RECALL_REARM_GOLD:
            self._recall_armed = True
        crossed = (float(prev.current_gold or 0.0) < _RECALL_GOLD_MIN
                   and gold >= _RECALL_GOLD_MIN)
        if self._recall_armed and crossed and not live.is_dead:
            self._recall_armed = False
            out.append(Alert(
                id="recall", category=RECALL_GOLD,
                text=f"{int(gold)}g banked — plan a back on a good timer",
                rationale="Sitting on gold is wasted power; back on a pushed wave "
                          "or after an objective to spend into your spike.",
                tone="info", priority=_PRIORITY[RECALL_GOLD]))

    def _objective(self, prev, live, out) -> None:
        t_now = live.objective_timers or {}
        t_prev = prev.objective_timers or {}
        d_now, d_prev = t_now.get("dragon"), t_prev.get("dragon")
        if (d_now is not None and d_prev is not None
                and 0 < d_now <= _DRAGON_WINDOW < d_prev):
            soul = (live.soul or {}).get("type") or "dragon"
            out.append(Alert(
                id="setup-dragon", category=OBJECTIVE_SETUP,
                text=f"Dragon ~{int(d_now)}s — rotate and ward now",
                rationale=f"Vision and position win objectives before they spawn; "
                          f"set up early for the {soul} drake.",
                tone="info", priority=_PRIORITY[OBJECTIVE_SETUP]))
        b_now, b_prev = t_now.get("baron"), t_prev.get("baron")
        if (b_now is not None and b_prev is not None and live.game_time >= _BARON_FIRST
                and 0 < b_now <= _BARON_WINDOW < b_prev):
            out.append(Alert(
                id="setup-baron", category=OBJECTIVE_SETUP,
                text=f"Baron ~{int(b_now)}s — get vision and a pick",
                rationale="Baron is decided on the setup: deny enemy vision and "
                          "look for a numbers advantage before starting it.",
                tone="info", priority=_PRIORITY[OBJECTIVE_SETUP]))

    def _low_hp(self, prev, live, out) -> None:
        if live.is_dead:
            return
        now = float((live.champion_stats or {}).get("health_pct") or 0.0)
        before = float((prev.champion_stats or {}).get("health_pct") or 0.0)
        if 0 < now <= _LOW_HP_PCT < before:
            out.append(Alert(
                id="low-hp", category=LOW_HP,
                text="Low HP — disengage and reset",
                rationale="Dying gives gold and tempo; a reset keeps your lead. "
                          "Live to spend your advantage, don't gamble it.",
                tone="bad", priority=_PRIORITY[LOW_HP]))

    def _death_review(self, prev, live, out) -> None:
        if live.deaths <= prev.deaths:
            return
        d = live.last_death or {}
        assisters = int(d.get("assisters") or 0)
        champ = d.get("killer_champ") or ""
        if assisters >= 1:
            text = f"Caught by a {assisters + 1}-man collapse"
            why = ("You were collapsed on without vision — ward the flanks and "
                   "don't push past river unseen while behind.")
        elif champ:
            text = f"Solo killed by {champ}"
            why = (f"You lost the 1v1 — respect {champ}'s cooldowns and only trade "
                   "when their key ability is down.")
        else:
            text = "You died — reset and reassess"
            why = "Take stock: back off, get vision, and don't force the next fight even."
        out.append(Alert(id=f"death-{live.deaths}", category=DEATH_REVIEW,
                         text=text, rationale=why, tone="bad",
                         priority=_PRIORITY[DEATH_REVIEW]))

    def _matchup(self, prev, live, out) -> None:
        # A once-per-game lane plan, pitched only in the opening minutes.
        if live.game_time > _MATCHUP_WINDOW:
            return
        m = live.matchup or {}
        if not m.get("opponent"):
            return
        playstyle = m.get("playstyle") or ""
        tempo = m.get("tempo") or ""
        out.append(Alert(
            id="matchup", category=MATCHUP_PLAN,
            text=f"vs {m['opponent']}: {playstyle or tempo}",
            rationale=tempo if playstyle else "",
            tone="info", priority=_PRIORITY[MATCHUP_PLAN]))
