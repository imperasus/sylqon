"""Deterministic matchup-aware rune-page selection.

The mirror image of ``core_select`` for runes: from the real op.gg rune pages
carried on the candidate build (``rune_page_options``), pick the page whose
defensive/utility runes best answer the enemy damage skew — but only when a
challenger page covers strictly MORE mandated rune-counter tags than the meta
page, clears the sample floor, and is not confidently worse on win rate
(Wilson-guarded).

Pure code, no LLM. Runs as a pre-step before ``loadout.from_candidate`` (right
after ``core_select``), so the whole pipeline — the AI's pool-constrained rune
filter, shard logic, variants — operates on a matchup-correct base page. A
balanced comp mandates nothing, so the meta page always stays.
"""
from __future__ import annotations

import logging

from sylqon.analysis.lane_counter import lane_opponent
from sylqon.analysis.select_util import adaptive_floor, confidently_worse
from sylqon.data import static
from sylqon.lcu.lobby import MatchContext
from sylqon.loadout import _safe_threat

log = logging.getLogger(__name__)

MIN_PAGE_GAMES = 20
MIN_PAGE_GAMES_FLOOR = 8
MIN_PAGE_SHARE = 0.03

_TAG_LABELS = {
    "magic_shield": "Anti-AP",
    "anti_burst": "Anti-burst",
    "anti_poke": "Anti-poke",
    "tenacity": "Tenacity",
}


def _poke_count(ctx: MatchContext) -> int:
    try:
        return sum(1 for e in ctx.enemies
                   if "poke" in (getattr(e, "threats", []) or []))
    except TypeError:  # pragma: no cover - mocked ctx
        return 0


def rune_requirements(ctx: MatchContext) -> set[str]:
    """Rune-counter tags the enemy comp (and lane opponent) mandate.

    The lane opponent's own threats count too — a bursty laner justifies Bone
    Plating even when the team as a whole isn't burst-heavy."""
    threat = _safe_threat(ctx)
    opp = lane_opponent(ctx)
    opp_threats = set(getattr(opp, "threats", []) or []) if opp is not None else set()

    reqs: set[str] = set()
    if threat.get("burst_ap") or threat.get("magic_threats", 0) >= 3 \
            or "burst_ap" in opp_threats:
        reqs.add("magic_shield")
    if threat.get("burst_ad") or "burst_ad" in opp_threats:
        reqs.add("anti_burst")
    if _poke_count(ctx) >= 2 or "poke" in opp_threats:
        reqs.add("anti_poke")
    if threat.get("heavy_cc_count", 0) >= 3:
        reqs.add("tenacity")
    return reqs


def _page_tags(page: dict) -> set[str]:
    """Rune-counter tags a page's minor runes carry (primary + secondary)."""
    out: set[str] = set()
    for rune in list(page.get("primary_runes") or []) + list(page.get("secondary_runes") or []):
        out |= set(static.RUNE_COUNTER_TAGS.get(rune, ()))
    return out


def _page_ids(page: dict) -> tuple:
    return (page.get("keystone"),
            tuple(page.get("primary_runes") or []),
            page.get("secondary_style"),
            tuple(page.get("secondary_runes") or []))


def select_rune_page(candidate: dict, ctx: MatchContext) -> tuple[dict | None, str]:
    """The rune page to use against this comp, or ``(None, "")`` to keep meta.
    Never raises; any structural surprise degrades to "keep meta"."""
    options = candidate.get("rune_page_options") or []
    if len(options) < 2:
        return None, ""

    reqs = rune_requirements(ctx)
    if not reqs:
        return None, ""  # nothing mandated → keep meta page

    meta_ids = _page_ids(candidate)
    meta_opt = next((o for o in options if _page_ids(o) == meta_ids), None)
    baseline = len(_page_tags(candidate) & reqs)

    total_games = sum(o.get("games") or 0 for o in options)
    min_games = adaptive_floor(total_games, cap=MIN_PAGE_GAMES,
                               floor=MIN_PAGE_GAMES_FLOOR)
    meta_wr = meta_opt.get("win_rate") if meta_opt else None
    meta_games = (meta_opt.get("games") or 0) if meta_opt else 0

    best: dict | None = None
    best_score = baseline
    for opt in options:
        if _page_ids(opt) == meta_ids:
            continue
        games = opt.get("games") or 0
        if games < min_games:
            continue
        if total_games and games / total_games < MIN_PAGE_SHARE:
            continue
        wr = opt.get("win_rate") or 0.0
        if meta_wr is not None and confidently_worse(wr, games, meta_wr, meta_games):
            continue
        score = len(_page_tags(opt) & reqs)
        if score > best_score:
            best, best_score = opt, score

    if best is None:
        return None, ""

    gained = (_page_tags(best) & reqs) - _page_tags(candidate)
    key = next((t for t in ("magic_shield", "anti_burst", "anti_poke", "tenacity")
                if t in gained), None)
    label = _TAG_LABELS.get(key, "Counter")
    reason = (
        f"{label} runes: {best['keystone']} page adds "
        f"{'/'.join(sorted(gained)) or 'matchup cover'} the meta page lacks "
        f"(op.gg: {best.get('games', 0)} games, "
        f"{round((best.get('win_rate') or 0.0) * 100, 1)}% WR)"
    )
    return best, reason


def apply_rune_selection(candidate: dict, ctx: MatchContext) -> dict:
    """Candidate build with the matchup-selected rune page folded in.

    Returns the candidate unchanged (same object) when the meta page stays;
    otherwise a copy whose keystone/primary_runes/secondary_style/
    secondary_runes/stat_shards reflect the chosen page, with ``rune_reason``
    recording why (surfaced in the UI and the decisions layer)."""
    page, reason = select_rune_page(candidate, ctx)
    if page is None:
        return candidate
    out = dict(candidate)
    out["keystone"] = page["keystone"]
    out["primary_runes"] = list(page["primary_runes"])
    out["secondary_style"] = page["secondary_style"]
    out["secondary_runes"] = list(page["secondary_runes"])
    out["stat_shards"] = list(page["stat_shards"])
    out["rune_reason"] = reason
    log.info("Matchup rune page selected for %s %s: %s",
             ctx.my_champion, ctx.my_role, reason)
    return out
