"""Deterministic coaching callouts from the scouted roster.

The Players tab used to *describe* the lobby ("X is on a 3-loss streak") and
leave the "so what?" to the reader. This module closes that gap: every callout
is an **action** with a **timing** and the **evidence** behind it, so the player
knows what to do, when, and why we said it.

    {"action": "Ward the river bush before 3:00 — their jungler starts bot side.",
     "timing": "3:00–4:00",
     "evidence": "Lee Sin, 0.78 aggression over 20 games",
     "kind": "jungle_threat", "priority": 80, "tone": "amber"}

Design rules:
  * **Pure and deterministic** — no DB, catalog or LLM. The caller resolves
    champion names, damage types and threat tags onto the cards.
  * **Evidence or silence** — a callout that cannot cite a number is not
    emitted. This is what keeps the tab from drifting back into vague vibes.
  * **Capped and ranked** — at most ``MAX_CALLOUTS``, highest priority first,
    so the panel stays glanceable instead of becoming a wall of advice.

Callouts are generated only where the data genuinely exists. Riot anonymizes
enemies during champ select, so enemy-history-driven advice (their jungler's
aggression, their one-tricks) appears in-game; ally-driven and champion-driven
advice works pre-game too.
"""
from __future__ import annotations

MAX_CALLOUTS = 5

# --- thresholds (see data/benchmarks for the distributions these sit on) ------
AGGRO_JUNGLER = 0.62        # aggression score marking a gank-heavy jungler
ONETRICK_GAMES = 40         # games on the current champ that signal deep mastery
ONETRICK_SHARE = 0.5        # or this share of their recent pool
COLD_STREAK = 3             # losses in a row before a lane is worth pressuring
HOT_STREAK = 3
HOT_WIN_RATE = 0.58
FED_KDA = 4.0               # live KDA marking a genuinely snowballing enemy
MIN_EVIDENCE_GAMES = 10     # never cite a rate computed on less than this

# Two same-damage-profile threats is the point where a defensive item stops
# being a luxury and starts being the correct second-item decision.
DAMAGE_STACK = 2

# Per-role ward advice against an aggressive jungler — where *this* player is
# actually vulnerable during the first clear.
_WARD_BY_ROLE = {
    "top": "ward the tri-brush and hug your side of the lane",
    "middle": "ward river before you push the wave in",
    "bottom": "ward tri-bush and don't push past river without vision",
    "utility": "sweep and place a deep river ward before level 3",
    "jungle": "track their first clear and take the opposite side",
}
_DEFAULT_WARD = "ward toward river before pushing"

# Priorities — higher surfaces first. Ordered by how badly ignoring the callout
# loses you the game, not by how interesting it is.
_P_DIVE = 90
_P_JUNGLE = 80
_P_ITEM = 70
_P_ONETRICK = 60
_P_FED = 55
_P_PRESSURE = 40
_P_ENABLE = 30


def _side(players: list[dict], side: str) -> list[dict]:
    return [p for p in players if (p.get("side") or "ally") == side and not p.get("hidden")]


def _by_role(players: list[dict], role: str) -> dict | None:
    return next((p for p in players if p.get("role") == role), None)


def _form_games(p: dict) -> int:
    return int((p.get("recent_form") or {}).get("games") or 0)


def _callout(kind, action, timing, evidence, priority, tone="accent") -> dict:
    return {"kind": kind, "action": action, "timing": timing,
            "evidence": evidence, "priority": priority, "tone": tone}


# ------------------------------------------------------------------ generators
def _dive_risk(enemies: list[dict]) -> list[dict]:
    """A premade enemy botlane coordinates all-ins the solo-queue pairing can't.
    The dive window opens the moment they hit level 2 together."""
    bot, sup = _by_role(enemies, "bottom"), _by_role(enemies, "utility")
    if not bot or not sup:
        return []
    group = bot.get("premade_group")
    if group is None or group != sup.get("premade_group"):
        return []
    return [_callout(
        "dive_risk",
        f"Enemy botlane ({bot.get('champion') or '?'} + {sup.get('champion') or '?'}) is a duo — "
        "hold the wave near your tower and respect the level-2 all-in.",
        "levels 2–3",
        f"{bot.get('name') or 'bot'} and {sup.get('name') or 'sup'} queued together",
        _P_DIVE, tone="enemy")]


def _jungle_threat(enemies: list[dict], my_role: str) -> list[dict]:
    """An aggressive enemy jungler turns the first clear into a gank timer."""
    jg = _by_role(enemies, "jungle")
    if not jg:
        return []
    aggression = jg.get("aggression")
    games = _form_games(jg)
    if aggression is None or aggression < AGGRO_JUNGLER or games < MIN_EVIDENCE_GAMES:
        return []
    ward = _WARD_BY_ROLE.get(my_role, _DEFAULT_WARD)
    return [_callout(
        "jungle_threat",
        f"{jg.get('champion') or 'Their jungler'} ganks early — {ward}.",
        "3:00–4:00",
        f"{jg.get('name') or 'jungler'}: {aggression:.2f} aggression over {games} games",
        _P_JUNGLE, tone="amber")]


def _itemization(enemies: list[dict]) -> list[dict]:
    """Turn the enemy damage/threat profile into the one build decision that
    actually changes: what the second item should be."""
    out: list[dict] = []
    ad = [e for e in enemies if e.get("damage_type") == "AD"]
    ap = [e for e in enemies if e.get("damage_type") == "AP"]
    healers = [e for e in enemies if "heavy_healing" in (e.get("threats") or [])]

    if len(ad) >= DAMAGE_STACK and len(ad) > len(ap):
        names = ", ".join(e.get("champion") or "?" for e in ad[:3])
        out.append(_callout(
            "itemization",
            "Buy armor into your second item — their damage is mostly physical.",
            "second item",
            f"{len(ad)} AD threats: {names}", _P_ITEM))
    elif len(ap) >= DAMAGE_STACK and len(ap) > len(ad):
        names = ", ".join(e.get("champion") or "?" for e in ap[:3])
        out.append(_callout(
            "itemization",
            "Buy magic resist into your second item — their damage is mostly magic.",
            "second item",
            f"{len(ap)} AP threats: {names}", _P_ITEM))

    if len(healers) >= DAMAGE_STACK:
        names = ", ".join(e.get("champion") or "?" for e in healers[:3])
        out.append(_callout(
            "itemization",
            "Rush anti-heal (Executioner's / Oblivion Orb) — they out-sustain you otherwise.",
            "first back",
            f"{len(healers)} healing threats: {names}", _P_ITEM))
    return out


def _one_tricks(enemies: list[dict]) -> list[dict]:
    """Deep mastery on the champion they're on means their spikes are real —
    respect them rather than testing them."""
    out: list[dict] = []
    for e in enemies:
        cc = e.get("current_champ") or {}
        games = int(cc.get("games") or 0)
        comfort = e.get("comfort") or {}
        share = float(comfort.get("share") or 0.0)
        deep = games >= ONETRICK_GAMES
        mains = share >= ONETRICK_SHARE and (comfort.get("champion") == e.get("champion"))
        if not (deep or mains):
            continue
        wr = cc.get("win_rate")
        bits = []
        if games:
            bits.append(f"{games} games on {e.get('champion') or 'it'}")
        if wr is not None and games >= MIN_EVIDENCE_GAMES:
            bits.append(f"{wr * 100:.0f}% WR")
        if mains and share:
            bits.append(f"{share * 100:.0f}% of their recent pool")
        if not bits:
            continue
        out.append(_callout(
            "one_trick",
            f"Don't duel {e.get('name') or 'them'} on {e.get('champion') or 'their champ'} early — "
            "they know the matchup better than the average player.",
            "laning phase",
            " · ".join(bits), _P_ONETRICK, tone="amber"))
    return out


def _fed_enemies(enemies: list[dict]) -> list[dict]:
    """A snowballing enemy changes how the map can be walked, right now."""
    out: list[dict] = []
    for e in enemies:
        kills, deaths, assists = e.get("kills"), e.get("deaths"), e.get("assists")
        if kills is None or deaths is None:
            continue
        kda = (kills + (assists or 0)) / max(1, deaths)
        if kda < FED_KDA or kills < 3:
            continue
        out.append(_callout(
            "fed_enemy",
            f"{e.get('champion') or 'An enemy'} is ahead — don't face-check alone, move as a group.",
            "now",
            f"{e.get('name') or 'they'} at {kills}/{deaths}/{assists or 0}",
            _P_FED, tone="enemy"))
    return out


def _pressure_targets(enemies: list[dict]) -> list[dict]:
    """A lane worth pressuring — but only with the death evidence behind it, so a
    plain 3-loss streak (well within variance) never triggers this."""
    out: list[dict] = []
    for e in enemies:
        form = e.get("recent_form") or {}
        streak = int(form.get("streak") or 0)
        recent_deaths, base_deaths = form.get("avg_deaths"), (e.get("avg_kda") or {}).get("deaths")
        if streak > -COLD_STREAK or recent_deaths is None or base_deaths is None:
            continue
        if recent_deaths <= base_deaths:
            continue
        out.append(_callout(
            "pressure",
            f"Pressure {e.get('role') or 'their'} lane — {e.get('name') or 'they'} are misplaying, not just unlucky.",
            "laning phase",
            f"{abs(streak)} losses, {recent_deaths} deaths/game vs {base_deaths} usual",
            _P_PRESSURE, tone="good"))
    return out


def _enable_allies(allies: list[dict]) -> list[dict]:
    """Who on your side is worth playing through."""
    out: list[dict] = []
    for a in allies:
        if a.get("is_self"):
            continue
        form = a.get("recent_form") or {}
        streak = int(form.get("streak") or 0)
        wr, games = form.get("win_rate") or 0.0, _form_games(a)
        if streak >= HOT_STREAK and wr >= HOT_WIN_RATE and games >= MIN_EVIDENCE_GAMES:
            out.append(_callout(
                "enable_ally",
                f"Play through {a.get('name') or 'your teammate'} ({a.get('role') or '?'}) — they're the hot hand.",
                "mid game",
                f"{streak} wins in a row, {wr * 100:.0f}% over {games} games",
                _P_ENABLE, tone="ally"))
    return out


# ----------------------------------------------------------------------- entry
def build_callouts(players: list[dict], my_role: str = "",
                   limit: int = MAX_CALLOUTS) -> list[dict]:
    """Prioritized, evidence-bearing coaching callouts for the scouted roster.

    ``players`` are scout cards (see the module docstring for the fields the
    caller resolves). Returns at most ``limit`` callouts, highest priority
    first; ties keep generator order so the output is stable for a given roster.
    """
    allies, enemies = _side(players, "ally"), _side(players, "enemy")
    out: list[dict] = []
    out += _dive_risk(enemies)
    out += _jungle_threat(enemies, my_role)
    out += _itemization(enemies)
    out += _one_tricks(enemies)
    out += _fed_enemies(enemies)
    out += _pressure_targets(enemies)
    out += _enable_allies(allies)
    out.sort(key=lambda c: -c["priority"])
    return out[:limit]
