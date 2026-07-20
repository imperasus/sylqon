"""Multi-factor ban scoring (pure, deterministic — no DB, no LLM).

The old ban list ranked purely by the player's own lane tier. A real ban weighs
several forces at once, and — crucially — distinguishes a **power ban** (a
meta-warping pick everyone removes regardless of who you are) from a **personal
ban** (a champion that specifically beats YOUR pool). This module scores a
candidate from four normalized factors and labels it by whichever force drives
it, so the UI can say *why* each ban is suggested.

Factors (each 0..1):
  * ``meta``          — lane tier strength (S+/S = power-ban fuel)
  * ``pool_counter``  — how hard it beats the player's own pool (personal-ban fuel)
  * ``contested``     — pick-rate proxy for "frequently picked/banned"
  * ``flex``          — plays multiple lanes, so it is harder to answer in draft

The runtime layer (:meth:`runtime.PipelineRunner._ban_suggestions`) gathers the
raw inputs team-wide and calls in here.
"""
from __future__ import annotations

# tier (op.gg 0 = OP) -> meta strength. Absent/unknown tiers get a low floor.
_TIER_META = {0: 1.0, 1: 0.85, 2: 0.6, 3: 0.4, 4: 0.25, 5: 0.15}

WEIGHTS = {"meta": 0.35, "pool_counter": 0.40, "contested": 0.15, "flex": 0.10}

# A pick-rate (percentage) at or above this reads as "everyone contests this".
_CONTESTED_FULL_PCT = 12.0
# A summed pool-counter advantage at or above this reads as a full personal threat.
_POOL_THREAT_FULL = 10.0


def score_ban(tier, pick_rate: float | None, pool_threat: float,
              is_flex: bool, plays_my_role: bool) -> tuple[float, dict]:
    """Return ``(total, factors)`` for one ban candidate. ``pool_threat`` is the
    summed advantage this champion has over the player's pool (only meaningful
    when it can play the player's role — else it can't fight the player's pick)."""
    meta = _TIER_META.get(tier if tier is not None else 9, 0.2)
    contested = min(1.0, max(0.0, (pick_rate or 0.0) / _CONTESTED_FULL_PCT))
    pool = (min(1.0, max(0.0, pool_threat) / _POOL_THREAT_FULL)
            if plays_my_role else 0.0)
    flex = 1.0 if is_flex else 0.0
    factors = {"meta": meta, "pool_counter": pool,
               "contested": contested, "flex": flex}
    total = sum(WEIGHTS[k] * factors[k] for k in factors)
    return round(total, 4), factors


def categorize(factors: dict) -> str:
    """Label a ban by the force that drives it: ``personal`` (beats your pool),
    ``power`` (meta-warping S/S+ pick) or ``meta`` (a strong pick worth denying).
    The dominant *weighted* contribution decides."""
    contrib = {k: WEIGHTS[k] * v for k, v in factors.items()}
    top = max(contrib, key=contrib.get)
    if top == "pool_counter" and factors["pool_counter"] > 0:
        return "personal"
    if factors["meta"] >= 0.85:
        return "power"
    return "meta"


_TIER_LABEL = {0: "S+", 1: "S", 2: "A", 3: "B"}


def ban_reason(name: str, tier, factors: dict, category: str,
               is_flex: bool, in_pool: bool) -> str:
    """A short, human reason that leads with the ban's category and cites the
    one or two factors actually driving it."""
    tier_label = _TIER_LABEL.get(tier)
    tier_txt = f"{tier_label}-tier" if tier_label else "a lane threat"

    if category == "personal":
        head = f"Bans for you — beats your pool and is {tier_txt} in this lane"
    elif category == "power":
        head = f"Power ban — {tier_txt} meta menace"
    else:
        head = f"Worth denying — {tier_txt}"

    extras = []
    if factors["contested"] >= 0.6:
        extras.append("heavily contested")
    if is_flex:
        extras.append("flexes multiple lanes")
    if category != "personal" and factors["pool_counter"] > 0:
        extras.append("also beats your pool")
    if not extras and in_pool:
        extras.append("also one of yours — denies a mirror")

    return head + ("; " + ", ".join(extras) if extras else "") + "."
