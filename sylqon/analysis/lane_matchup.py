"""Lane-by-lane matchup edge — the analytical core of the Players tab.

For each role we blend up to four independent, individually confidence-weighted
signals into a single edge in ``[-1, 1]`` (positive = ally-favored):

  1. **champion matchup** — head-to-head lane advantage from the counters DB
     (op.gg / hosted-meta seeded), weighted by the stored matchup sample size;
  2. **form delta** — recent-form win-rate gap, shrunk toward 50% by sample size
     so a 3-game streak never outweighs a real matchup signal;
  3. **rank delta** — solo-queue tier/division gap between the two laners;
  4. **champion experience delta** — games + win rate each player has on the
     champion they are actually on.

Every signal is optional. Whatever is missing simply does not vote, and the
lane carries an aggregate ``confidence`` in ``[0, 1]`` so the UI can honestly
show *"even · low data"* instead of inventing a lean from noise. This is the
honesty contract: the edge is only as loud as the evidence behind it.

The module is **pure and deterministic** — no I/O, no catalog, no DB session.
The caller resolves champion ids/names and injects a ``matchup_fn`` lookup, so
the whole blend is unit-testable without a database.
"""
from __future__ import annotations

from collections.abc import Callable

# --- component base weights (relative importance when fully confident) --------
W_MATCHUP = 0.50    # the champion head-to-head is the primary lane read
W_FORM = 0.20
W_RANK = 0.20
W_EXPERIENCE = 0.10
W_TOTAL = W_MATCHUP + W_FORM + W_RANK + W_EXPERIENCE

# --- champion-matchup mapping -------------------------------------------------
MATCHUP_FULL = 5.0          # advantage_score of ±5 (of ±10) → a maxed ±1 edge
MATCHUP_GAMES_FULL = 800    # matchup sample size at which we fully trust it
MATCHUP_MIN_CONF = 0.30     # a known small sample still carries some weight
MATCHUP_NO_GAMES_CONF = 0.50  # DB estimate exists but sample size is unknown

# --- form mapping -------------------------------------------------------------
FORM_SHRINK_K = 10.0        # pseudo-games pulling a WR toward 0.5 (Bayesian prior)
FORM_SPAN = 0.15            # a 15pp shrunk WR gap → a maxed ±1 form edge
FORM_GAMES_FULL = 20        # per-side games at which the form read is fully trusted
FORM_ONE_SIDED_CONF = 0.20  # ally form with no enemy form (champ select) → faint

# --- rank mapping -------------------------------------------------------------
RANK_SPAN = 8.0             # a two-tier (8-division) gap → a maxed ±1 rank edge
RANK_CONF = 0.80            # both ranks known → a confident, if coarse, signal
_TIERS = ["IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD",
          "DIAMOND", "MASTER", "GRANDMASTER", "CHALLENGER"]
_TIER_INDEX = {t: i for i, t in enumerate(_TIERS)}
_DIVISIONS = {"IV": 0, "III": 1, "II": 2, "I": 3}

# --- experience mapping -------------------------------------------------------
EXP_GAMES_FULL = 50.0       # games on the current champ at which mastery maxes
EXP_SPAN = 0.30             # a full mastery-score gap → a maxed ±1 experience edge
EXP_GAMES_FULL_CONF = 30    # per-side games at which the experience read is trusted

# --- aggregation --------------------------------------------------------------
# Confidence saturates: a single strong signal (a well-sampled matchup, a clear
# rank gap) already clears the floor, and corroborating signals push it toward 1
# — but a lone faint signal never does. `conf_weight / (conf_weight + K)` is the
# soft-saturation curve; K is the conf_weight at which confidence reaches 0.5.
CONF_SATURATION = 0.25
CONF_FLOOR = 0.25           # below this aggregate confidence → honest "even · low data"
EDGE_FLOOR = 0.15           # |edge| below this (with enough confidence) → "even"
MAX_REASONS = 3

MatchupFn = Callable[[int, int, str], dict | None]


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _shrunk_wr(form: dict | None) -> tuple[float, int] | None:
    """Sample-size-shrunk win rate: ``(adjusted_wr, games)`` pulled toward 0.5 by
    ``FORM_SHRINK_K`` pseudo-games, or ``None`` when there are no games. This is
    what stops a 3-0 streak from reading as a 100% laner."""
    if not form:
        return None
    games = int(form.get("games") or 0)
    if games <= 0:
        return None
    wr = form.get("win_rate")
    if wr is None:
        return None
    wins = wr * games
    adj = (wins + 0.5 * FORM_SHRINK_K) / (games + FORM_SHRINK_K)
    return adj, games


def _rank_steps(rank: dict | None) -> int | None:
    """Absolute ladder position in 'divisions': ``tier * 4 + division``. Master+
    have no divisions, so they sit at the tier floor. ``None`` if unranked."""
    if not rank:
        return None
    tier = str(rank.get("tier") or "").upper()
    if tier not in _TIER_INDEX:
        return None
    div = _DIVISIONS.get(str(rank.get("division") or "").upper(), 0)
    return _TIER_INDEX[tier] * 4 + div


def _mastery_score(cc: dict | None) -> float | None:
    """A 0..1-ish champion-mastery read blending shrunk WR and games volume. Used
    only as a delta between the two laners, so the absolute scale is unimportant —
    only that more games + higher WR ranks above fewer games / lower WR."""
    if not cc:
        return None
    games = cc.get("games")
    if games is None:
        return None
    games = int(games)
    if games <= 0:
        return None
    wr = cc.get("win_rate")
    wr = 0.5 if wr is None else wr
    adj = (wr * games + 0.5 * FORM_SHRINK_K) / (games + FORM_SHRINK_K)
    volume = _clamp(games / EXP_GAMES_FULL, 0.0, 1.0)
    # Center on 0.5 so an even WR contributes only via volume, then fold volume in.
    return 0.5 + (adj - 0.5) * (0.5 + 0.5 * volume)


def _games_suffix(games: int | None) -> str:
    if not games:
        return ""
    if games >= 1000:
        return f", {games / 1000:.1f}k games"
    return f", {games} games"


def lane_edge(ally: dict | None, enemy: dict | None,
              matchup_fn: MatchupFn) -> dict:
    """Blend the available signals for one lane into an edge + confidence + the
    human-readable reasons behind it.

    ``ally`` / ``enemy`` are cards with any of these optional keys::

        champion_id: int
        champion:    str   (display name, for the reason text)
        recent_form: {games, win_rate}
        rank:        {tier, division}
        current_champ: {games, win_rate}

    ``matchup_fn(ally_cid, enemy_cid, role)`` returns
    ``{"advantage": float(-10..10), "games": int | None}`` or ``None``.
    """
    ally = ally or {}
    enemy = enemy or {}
    # (edge, confidence, base_weight, reason) per contributing signal.
    parts: list[tuple[float, float, float, str | None]] = []

    _matchup_part(parts, ally, enemy, matchup_fn)
    _form_part(parts, ally, enemy)
    _rank_part(parts, ally, enemy)
    _experience_part(parts, ally, enemy)

    weighted = sum(edge * conf * w for edge, conf, w, _ in parts)
    conf_weight = sum(conf * w for _, conf, w, _ in parts)
    edge = weighted / conf_weight if conf_weight > 0 else 0.0
    # Aggregate confidence saturates on the evidence mass we gathered: one strong
    # signal is enough to speak up, several corroborating ones push toward 1, and
    # a single faint signal stays below the floor → honest "even · low data".
    confidence = conf_weight / (conf_weight + CONF_SATURATION)

    if confidence < CONF_FLOOR:
        lean = "even"
    elif edge >= EDGE_FLOOR:
        lean = "ally"
    elif edge <= -EDGE_FLOOR:
        lean = "enemy"
    else:
        lean = "even"

    reasons = [r for _, _, _, r in sorted(
        parts, key=lambda p: abs(p[0] * p[1]), reverse=True) if r][:MAX_REASONS]

    return {
        "edge": round(edge, 3),
        "confidence": round(confidence, 3),
        "lean": lean,
        "low_data": confidence < CONF_FLOOR,
        "reasons": reasons,
    }


def _matchup_part(parts: list, ally: dict, enemy: dict, matchup_fn: MatchupFn) -> None:
    a_cid, e_cid = ally.get("champion_id"), enemy.get("champion_id")
    role = ally.get("role") or enemy.get("role") or ""
    if not a_cid or not e_cid:
        return
    try:
        mu = matchup_fn(a_cid, e_cid, role)
    except Exception:
        mu = None
    if not mu or mu.get("advantage") is None:
        return
    adv = float(mu["advantage"])
    edge = _clamp(adv / MATCHUP_FULL, -1.0, 1.0)
    games = mu.get("games")
    if games:
        conf = _clamp(games / MATCHUP_GAMES_FULL, MATCHUP_MIN_CONF, 1.0)
    else:
        conf = MATCHUP_NO_GAMES_CONF
    reason = None
    if abs(adv) >= 0.5:
        a_name = ally.get("champion") or "ally"
        e_name = enemy.get("champion") or "enemy"
        verb = "beats" if adv > 0 else "loses to"
        reason = f"{a_name} {verb} {e_name} in lane ({adv:+.1f}{_games_suffix(games)})"
    parts.append((edge, conf, W_MATCHUP, reason))


def _form_part(parts: list, ally: dict, enemy: dict) -> None:
    af = _shrunk_wr(ally.get("recent_form"))
    ef = _shrunk_wr(enemy.get("recent_form"))
    if af is None:
        return
    a_adj, a_games = af
    if ef is not None:
        e_adj, e_games = ef
        edge = _clamp((a_adj - e_adj) / FORM_SPAN, -1.0, 1.0)
        conf = _clamp(min(a_games, e_games) / FORM_GAMES_FULL, 0.0, 1.0)
        reason = None
        if abs(a_adj - e_adj) >= 0.05:
            better, worse = ("ally", enemy) if a_adj > e_adj else ("enemy", ally)
            name = (ally if better == "ally" else enemy).get("name") or better
            reason = f"{name} in better recent form ({a_adj * 100:.0f}% vs {e_adj * 100:.0f}%)"
        parts.append((edge, conf, W_FORM, reason))
    else:
        # One-sided (champ select: no enemy history). A faint nudge only.
        edge = _clamp((a_adj - 0.5) / FORM_SPAN, -1.0, 1.0)
        reason = None
        if abs(a_adj - 0.5) >= 0.07:
            name = ally.get("name") or "ally"
            trend = "hot" if a_adj > 0.5 else "cold"
            reason = f"{name} is {trend} lately ({a_adj * 100:.0f}% form)"
        parts.append((edge, FORM_ONE_SIDED_CONF, W_FORM, reason))


def _rank_part(parts: list, ally: dict, enemy: dict) -> None:
    a_steps = _rank_steps(ally.get("rank"))
    e_steps = _rank_steps(enemy.get("rank"))
    if a_steps is None or e_steps is None:
        return
    edge = _clamp((a_steps - e_steps) / RANK_SPAN, -1.0, 1.0)
    reason = None
    if abs(a_steps - e_steps) >= 2:  # at least half a tier apart to be worth saying
        a_label = ally.get("rank", {}).get("label") or "ally"
        e_label = enemy.get("rank", {}).get("label") or "enemy"
        parts_txt = "out-ranks" if a_steps > e_steps else "is out-ranked by"
        reason = f"{ally.get('name') or 'ally'} {parts_txt} lane ({a_label} vs {e_label})"
    parts.append((edge, RANK_CONF, W_RANK, reason))


def _experience_part(parts: list, ally: dict, enemy: dict) -> None:
    am = _mastery_score(ally.get("current_champ"))
    em = _mastery_score(enemy.get("current_champ"))
    if am is None or em is None:
        return
    edge = _clamp((am - em) / EXP_SPAN, -1.0, 1.0)
    a_games = int((ally.get("current_champ") or {}).get("games") or 0)
    e_games = int((enemy.get("current_champ") or {}).get("games") or 0)
    conf = _clamp(min(a_games, e_games) / EXP_GAMES_FULL_CONF, 0.0, 1.0)
    reason = None
    gap = a_games - e_games
    if abs(gap) >= 15:
        name = (ally if gap > 0 else enemy).get("name") or "player"
        champ = (ally if gap > 0 else enemy).get("champion") or "their champ"
        more = abs(gap)
        reason = f"{name} far more practised on {champ} (+{more} games)"
    parts.append((edge, conf, W_EXPERIENCE, reason))


def compute_lanes(ally_by_role: dict, enemy_by_role: dict,
                  matchup_fn: MatchupFn, roles: list[str]) -> dict:
    """Edge per role for the given ally/enemy lane cards. Returns
    ``{role: lane_edge(...)}`` for every role that has at least one side present.
    """
    out: dict = {}
    for role in roles:
        a = ally_by_role.get(role)
        e = enemy_by_role.get(role)
        if not a and not e:
            continue
        out[role] = lane_edge(a, e, matchup_fn)
    return out
