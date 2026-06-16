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
                   "stack MR/sustain and look for hard-engage angles."),
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
