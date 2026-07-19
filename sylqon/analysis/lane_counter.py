"""Lane-matchup counter layer (deterministic, pure — no LLM, no network).

The direct lane opponent dominates the laning phase, yet the team-level threat
summary dilutes them to one voice in five. This module gives the lane opponent
their real weight in the loadout:

- :func:`lane_requirements` — counter-tag mandates derived from the lane
  opponent's own threat profile, always urgent (they must arrive within the
  first two purchases, not as a 5th item);
- :func:`combined_requirements` — lane + team requirements, deduped, lane
  first, drop-in compatible with ``loadout._enforce_counter_items`` and
  ``core_select``;
- :func:`matchup_starting_items` — swaps the Doran's starter when the lane
  profile demands it (poke lane → Doran's Shield on AD champions);
- :func:`first_back_items` — the cheap counter COMPONENTS answering the lane
  on the first recall, surfaced as an item-set block and in the AI prompt;
- :func:`lane_directives` — prompt lines teaching the model (and, via the
  post-lock view, the player) how to punish the specific lane matchup.

Everything degrades to the existing team-level behaviour when there is no
identifiable lane opponent (blind pick, jungle mirror unknown, hidden enemy).
"""
from __future__ import annotations

import logging

from sylqon.data import static
from sylqon.lcu.lobby import MatchContext
from sylqon.loadout import _counter_requirements, _safe_threat

log = logging.getLogger(__name__)

Requirement = tuple[set[str], bool]


def lane_opponent(ctx: MatchContext):
    """The same-role enemy pick, or ``None``. Tolerant of stub contexts."""
    role = getattr(ctx, "my_role", "") or ""
    if not role:
        return None
    try:
        for e in ctx.enemies:
            if getattr(e, "role", None) == role:
                return e
    except TypeError:  # mocked ctx without a real enemy list
        return None
    return None


def _opp_threats(opp) -> set[str]:
    try:
        return set(getattr(opp, "threats", []) or [])
    except TypeError:  # pragma: no cover - defensive
        return set()


def lane_requirements(ctx: MatchContext) -> list[Requirement]:
    """Counter-tag requirements mandated by the LANE opponent alone.

    All survival-critical tags are urgent: a lane threat is felt from minute
    one, so its answer belongs at the front of the situational block. A lane
    tank is a soft requirement (their resists stack toward mid-game)."""
    opp = lane_opponent(ctx)
    if opp is None:
        return []
    threats = _opp_threats(opp)
    reqs: list[Requirement] = []
    if "heavy_healing" in threats:
        reqs.append(({"anti_heal"}, True))
    if "suppression" in threats:
        reqs.append(({"anti_suppression"}, True))
    if "burst_ad" in threats or "burst_ap" in threats:
        reqs.append(({"anti_burst"}, True))
    if "tank" in threats:
        reqs.append(({"percent_pen", "tank_shred"}, False))
    return reqs


def combined_requirements(ctx: MatchContext) -> list[Requirement]:
    """Lane requirements first (they carry the urgency of the laning phase),
    then the team-level requirements, deduped by accepted-tag set. When the
    same tag set appears in both, the lane entry wins — which only ever
    upgrades a soft requirement to urgent, never the reverse."""
    seen: set[frozenset[str]] = set()
    out: list[Requirement] = []
    for req in lane_requirements(ctx) + _counter_requirements(_safe_threat(ctx)):
        key = frozenset(req[0])
        if key in seen:
            continue
        seen.add(key)
        out.append(req)
    return out


def matchup_starting_items(starting: list[dict],
                           ctx: MatchContext) -> tuple[list[dict], str]:
    """The starting block adjusted for the lane matchup.

    Returns ``(items, reason)``; ``reason`` is ``""`` when nothing changed.
    Only ever swaps WITHIN the Doran's trio — jungle pets, the support quest
    item and consumables are never touched. Current rule set:

    - poke lane + AD champion on a Doran's Blade start → Doran's Shield (the
      regen outvalues the AD while you can't trade back into poke). AP
      champions keep Doran's Ring: losing the mana regen into a poke lane
      costs more than the HP regen gains.
    """
    opp = lane_opponent(ctx)
    if opp is None:
        return list(starting), ""
    champ_type = static.CHAMPION_DAMAGE_TYPE.get(
        getattr(ctx, "my_champion", "") or "", "mixed")

    if "poke" in _opp_threats(opp) and champ_type == "ad":
        out = []
        swapped = False
        for it in starting:
            if not swapped and it.get("id") == static.DORANS_BLADE["id"]:
                out.append(dict(static.DORANS_SHIELD))
                swapped = True
            else:
                out.append(it)
        if swapped:
            reason = (f"Doran's Shield start: {getattr(opp, 'name', 'lane opponent')} "
                      f"is a poke threat — regen beats AD you can't trade back")
            log.info("Matchup starter: %s", reason)
            return out, reason
    return list(starting), ""


def first_back_items(ctx: MatchContext) -> list[dict]:
    """Up to three cheap counter components for the first recall, answering
    the LANE opponent specifically (resist piece first — you must survive the
    lane before you win it — then anti-heal, then pen, then QSS)."""
    opp = lane_opponent(ctx)
    if opp is None:
        return []
    threats = _opp_threats(opp)
    champ_type = static.CHAMPION_DAMAGE_TYPE.get(
        getattr(ctx, "my_champion", "") or "", "mixed")

    out: list[dict] = []
    seen: set[int] = set()

    def add(item: dict | None) -> None:
        if item and item["id"] not in seen:
            out.append(dict(item))
            seen.add(item["id"])

    for burst in ("burst_ad", "burst_ap"):
        if burst in threats:
            add(static.LANE_RESIST_COMPONENT[burst])
    if "heavy_healing" in threats:
        add(static.COUNTER_COMPONENTS["anti_heal"].get(champ_type))
    if "tank" in threats:
        add(static.COUNTER_COMPONENTS["percent_pen"].get(champ_type))
    if "suppression" in threats:
        add(static.COUNTER_COMPONENTS["anti_suppression"].get(champ_type))
    return out[:3]


def lane_directives(ctx: MatchContext) -> list[str]:
    """Prompt/coaching lines for the specific lane matchup (empty when the
    opponent is unknown)."""
    opp = lane_opponent(ctx)
    if opp is None:
        return []
    name = getattr(opp, "name", "lane opponent")
    threats = _opp_threats(opp)
    d: list[str] = []
    if "poke" in threats:
        d.append(f"{name} pokes: sustain start and an early resist component "
                 "outvalue damage — do not trade HP for CS before your spike.")
    if "burst_ad" in threats:
        d.append(f"{name} all-ins with physical burst: an early Chain Vest "
                 "(first back) removes their kill window; never sit at half HP.")
    if "burst_ap" in threats:
        d.append(f"{name} all-ins with magic burst: an early Negatron Cloak "
                 "(first back) removes their kill window.")
    if "heavy_healing" in threats:
        d.append(f"{name} sustains through trades: buy the anti-heal COMPONENT "
                 "on the first back, not as a 4th item.")
    if "tank" in threats:
        d.append(f"{name} stacks resists: your % penetration option must be "
                 "ordered early among situational picks.")
    if "suppression" in threats:
        d.append(f"{name} has a suppression: QSS is the only counter — "
                 "tenacity and Cleanse do nothing against it.")
    return d
