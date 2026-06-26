"""Pure draft-intelligence heuristics for the live champ-select board.

Everything here is deterministic and network-free so it can run on every visible
draft change (no Ollama, no DB). The runtime layer (``runtime.PipelineRunner``)
enriches the output of :func:`classify_comp` / :func:`counter_pick_advice` with
DB-backed ban suggestions and flex warnings.

Inputs are ``lobby.ChampPick`` instances, but every accessor also accepts the
plain dict shape ``{"name", "tags", "threats", "damage_type"}`` so callers can
synthesise a pick (e.g. the local player's hovered champion) without building a
full dataclass.
"""
from __future__ import annotations

from sylqon.data import static


# -- shape-agnostic accessors -----------------------------------------------
def _name(p) -> str:
    return p["name"] if isinstance(p, dict) else p.name


def _tags(p) -> set:
    return set(p["tags"] if isinstance(p, dict) else p.tags)


def _threats(p) -> set:
    return set(p["threats"] if isinstance(p, dict) else p.threats)


def _damage(p) -> str:
    return p["damage_type"] if isinstance(p, dict) else p.damage_type


# -- composition classification ---------------------------------------------
# archetype -> (label, the game-plan it forces on the OTHER team)
_ARCHETYPES = {
    "hard_engage": ("Hard Engage / Dive",
                    "Respect their all-in: itemize survivability, hold a "
                    "disengage/peel tool and don't get caught grouped."),
    "poke_siege": ("Poke / Siege",
                   "Force engage onto them — they fold once you close the gap; "
                   "stack sustain/shields and look for hard-engage angles."),
    "pick": ("Pick / Assassinate",
             "Never walk alone: ward deep, group, and bring a "
             "Zhonya/GA/QSS to survive the first burst."),
    "split_push": ("Split Push",
                   "Match their side-laner or force 5v4 mid; track the splitter "
                   "and trade objectives, don't chase."),
    "protect_carry": ("Protect the Carry",
                      "Dive past the peel onto the hyper-carry, or out-scale — "
                      "bring anti-heal and dive/flank threats."),
    "teamfight": ("Teamfight / Wombo",
                  "Don't group into their AoE: split the map, pick before "
                  "fights and bring flash-clears / spread positioning."),
    "balanced": ("Balanced", "No single win condition — play the standard "
                             "lane-and-objective game."),
    "unknown": ("Reading…", "Too few picks revealed to read the composition."),
}


def classify_comp(picks: list) -> dict:
    """Read a team's win-condition archetype from class tags + threat flags.

    Returns ``{archetype, label, confidence, counter_plan, signals}`` where
    ``confidence`` is 0-100 (margin of the winning archetype over the field)."""
    picks = [p for p in picks if p]
    if len(picks) < 2:
        label, plan = _ARCHETYPES["unknown"]
        return {"archetype": "unknown", "label": label, "confidence": 0,
                "counter_plan": plan, "signals": []}

    tags = [_tags(p) for p in picks]
    threats = [_threats(p) for p in picks]
    names = [_name(p) for p in picks]

    poke = sum(1 for i, n in enumerate(names)
               if n in static.HEAVY_POKE or "poke" in threats[i])
    engage = sum(1 for i in range(len(picks))
                 if "heavy_cc" in threats[i] and (tags[i] & {"Tank", "Fighter"}))
    suppression = sum(1 for t in threats if "suppression" in t)
    assassins = sum(1 for i in range(len(picks))
                    if ("Assassin" in tags[i])
                    or (threats[i] & {"burst_ad", "burst_ap"} and not (tags[i] & {"Tank", "Fighter"})))
    tanks = sum(1 for i in range(len(picks)) if "tank" in threats[i] or "Tank" in tags[i])
    enchanters = sum(1 for i in range(len(picks))
                     if "Support" in tags[i] and "heavy_healing" in threats[i])
    marksmen = sum(1 for t in tags if "Marksman" in t)
    splitters = sum(1 for n in names if n in static.SPLIT_PUSH_CHAMPS)

    scores = {
        "hard_engage": engage * 2 + suppression,
        "poke_siege": poke * 2,
        "pick": assassins * 2 + suppression,
        "split_push": splitters * 2,
        "protect_carry": (enchanters + (1 if marksmen else 0)) * 2 if enchanters and marksmen else 0,
        "teamfight": tanks + marksmen,
    }
    best, top = max(scores.items(), key=lambda kv: kv[1])
    if top < 2:
        best = "balanced"
        confidence = 0
    else:
        ordered = sorted(scores.values(), reverse=True)
        margin = top - (ordered[1] if len(ordered) > 1 else 0)
        confidence = max(20, min(100, top * 18 + margin * 12))

    signals = []
    if poke >= 2:
        signals.append(f"{poke} poke/siege threats")
    if engage >= 1:
        signals.append(f"{engage} hard-engage frontline")
    if assassins >= 2:
        signals.append(f"{assassins} burst/assassin threats")
    if tanks >= 2:
        signals.append(f"{tanks} tanks")
    if splitters >= 2:
        signals.append(f"{splitters} side-lane threats")
    if enchanters and marksmen:
        signals.append("enchanter + carry peel core")
    if suppression:
        signals.append("point-click lockdown")

    label, plan = _ARCHETYPES[best]
    return {"archetype": best, "label": label, "confidence": int(confidence),
            "counter_plan": plan, "signals": signals}


# -- counter-pick timing -----------------------------------------------------
def counter_pick_advice(ctx) -> dict:
    """Translate the draft pick-order into actionable counter-pick guidance.

    ``ctx`` is a ``lobby.MatchContext``. Returns ``{phase, headline, detail}``;
    ``phase`` is one of ``counter`` / ``blind`` / ``waiting`` / ``locked``."""
    if ctx.locked:
        return {"phase": "locked", "headline": "Locked in",
                "detail": "Your pick is final — focus on the loadout."}
    if not ctx.my_turn:
        revealed = sum(1 for e in ctx.enemies if e.locked)
        return {"phase": "waiting", "headline": "Not your turn yet",
                "detail": f"{revealed} enemy pick(s) revealed so far — keep options open."}
    if ctx.enemy_picks_after_me == 0:
        return {"phase": "counter", "headline": "Counter-pick window",
                "detail": "Every enemy is revealed — safe to lock a hard counter."}
    return {"phase": "blind",
            "headline": f"{ctx.enemy_picks_after_me} enemy pick(s) come after you",
            "detail": "Blind spot ahead — favour a flexible/safe pick over a greedy "
                      "counter that can be countered back."}


# -- head-to-head draft balance ---------------------------------------------
# Short archetype labels for the driver chips (full labels live in _ARCHETYPES).
_ARCH_SHORT = {
    "hard_engage": "Engage", "poke_siege": "Poke", "pick": "Pick",
    "split_push": "Split", "protect_carry": "Protect", "teamfight": "Teamfight",
    "balanced": "Balanced", "unknown": "?",
}

# Archetype rock-paper-scissors. A listed (A, B) pair means archetype A is
# favoured into archetype B (the mirror is automatically the inverse). Any
# unlisted pair is neutral. Kept deliberately small and one-directional.
_ARCH_MATCHUP = {
    ("hard_engage", "poke_siege"),     # close the gap, the pokers fold
    ("hard_engage", "protect_carry"),  # dive past the peel onto the carry
    ("poke_siege", "split_push"),      # siege objectives faster than they split
    ("poke_siege", "teamfight"),       # whittle them down before they group
    ("pick", "split_push"),            # catch the lone side-laner
    ("pick", "poke_siege"),            # catch the immobile pokers
    ("pick", "protect_carry"),         # pick the carry out of formation
    ("teamfight", "pick"),             # numbers win the clean 5v5
    ("teamfight", "hard_engage"),      # better sustained AoE in the fight
    ("split_push", "teamfight"),       # 1-3-1, never take the 5v5
    ("split_push", "protect_carry"),   # they can't answer a side lane
    ("protect_carry", "poke_siege"),   # out-sustain the poke
}

# Mapping from total accumulated edge to a win-probability point spread. The
# band is intentionally narrow — this is a draft heuristic, not a real model, so
# it must never claim a blowout.
_EDGE_TO_PCT = 6.0
_WIN_PCT_FLOOR, _WIN_PCT_CEIL = 35, 65


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _team_size(summary: dict) -> int:
    return (summary.get("physical_threats", 0) + summary.get("magic_threats", 0)
            + summary.get("mixed_threats", 0))


def draft_balance(ally_comp: dict, enemy_comp: dict,
                  ally_summary: dict, enemy_summary: dict,
                  *, lane_advantage: float | None = None) -> dict:
    """Deterministic head-to-head read of the two compositions.

    Blends an archetype rock-paper-scissors edge (scaled by how confidently each
    comp was read), damage-profile balance, frontline presence and a CC
    differential into a single estimated win probability. ``lane_advantage``
    (an op.gg lane edge, roughly [-10, 10]) is folded in when available
    (post-lock). Pure and network-free, mirroring :func:`classify_comp`.

    Returns ``{win_pct, edge, label, tone, drivers, confidence}`` where
    ``win_pct`` is clamped to [35, 65], ``drivers`` is a short signed list
    ``[{text, sign}]`` (strongest first) and ``confidence`` (0-100) reflects how
    much of the draft is revealed."""
    ally_comp = ally_comp or {}
    enemy_comp = enemy_comp or {}
    ally_summary = ally_summary or {}
    enemy_summary = enemy_summary or {}

    drivers: list[tuple[float, str]] = []  # (signed magnitude, text)
    edge = 0.0

    # 1. Archetype clash, weighted by the weaker of the two reads.
    a_arch = ally_comp.get("archetype", "unknown")
    e_arch = enemy_comp.get("archetype", "unknown")
    conf_w = min(ally_comp.get("confidence", 0), enemy_comp.get("confidence", 0)) / 100.0
    if (a_arch, e_arch) in _ARCH_MATCHUP:
        arch = 1.0 * conf_w
        drivers.append((arch, f"{_ARCH_SHORT[a_arch]} > {_ARCH_SHORT[e_arch]}"))
        edge += arch
    elif (e_arch, a_arch) in _ARCH_MATCHUP:
        arch = -1.0 * conf_w
        drivers.append((arch, f"{_ARCH_SHORT[e_arch]} > {_ARCH_SHORT[a_arch]}"))
        edge += arch

    # 2. Damage profile. Mixed AD/AP forces split itemisation; a mono-damage
    #    enemy can be answered with a single resist (good for you), a mono-damage
    #    ally is the team that gets itemised against (bad for you).
    a_ad, a_ap = ally_summary.get("physical_threats", 0), ally_summary.get("magic_threats", 0)
    e_ad, e_ap = enemy_summary.get("physical_threats", 0), enemy_summary.get("magic_threats", 0)
    if a_ad >= 1 and a_ap >= 1:
        drivers.append((0.4, "Mixed damage"))
        edge += 0.4
    if _team_size(enemy_summary) >= 3 and (e_ad == 0 or e_ap == 0):
        drivers.append((0.4, "Enemy mono-damage"))
        edge += 0.4
    if _team_size(ally_summary) >= 3 and (a_ad == 0 or a_ap == 0):
        drivers.append((-0.4, "Mono-damage"))
        edge -= 0.4

    # 3. Frontline — no frontline is a structural liability.
    a_front, e_front = ally_summary.get("frontline", 0), enemy_summary.get("frontline", 0)
    if _team_size(ally_summary) >= 3 and a_front == 0:
        drivers.append((-0.6, "No frontline"))
        edge -= 0.6
    elif a_front >= 1 and e_front == 0 and _team_size(enemy_summary) >= 3:
        drivers.append((0.4, "Frontline edge"))
        edge += 0.4

    # 4. CC differential.
    cc_diff = ally_summary.get("heavy_cc_count", 0) - enemy_summary.get("heavy_cc_count", 0)
    if abs(cc_diff) >= 2:
        cc = _clamp(cc_diff, -2, 2) * 0.2
        drivers.append((cc, "CC edge" if cc_diff > 0 else "CC deficit"))
        edge += cc

    # 5. Lane matchup edge (post-lock only).
    if lane_advantage is not None and abs(lane_advantage) >= 1.5:
        lane = _clamp(lane_advantage, -10, 10) * 0.1
        drivers.append((lane, "Lane lead" if lane > 0 else "Lane deficit"))
        edge += lane

    win_pct = int(round(_clamp(50 + edge * _EDGE_TO_PCT, _WIN_PCT_FLOOR, _WIN_PCT_CEIL)))
    if win_pct >= 55:
        label, tone = "FAVOURED", "good"
    elif win_pct <= 45:
        label, tone = "BEHIND", "bad"
    else:
        label, tone = "EVEN", "amber"

    revealed = _team_size(ally_summary) + _team_size(enemy_summary)
    confidence = int(round(min(100, revealed / 10 * 100)))

    drivers.sort(key=lambda d: abs(d[0]), reverse=True)
    return {
        "win_pct": win_pct,
        "edge": round(edge, 2),
        "label": label,
        "tone": tone,
        "confidence": confidence,
        "drivers": [{"text": t, "sign": 1 if m > 0 else -1} for m, t in drivers[:4]],
    }
