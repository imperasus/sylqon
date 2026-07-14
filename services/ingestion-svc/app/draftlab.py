"""Draft Lab core — live analysis + permalink codec for /draft and /d/{code}.

Pure functions over the ported draft engine (``app.draftintel``): the web page
and the JSON API both call :func:`analyze`, so the browser never re-implements
the engine (no JS-port drift). The permalink packs the board into a short,
URL-safe string of champion ids — no database row, no expiry, fork-friendly.

Framing (docs/WEB_DRAFT_TERV.md §6): every number here scores *compositions*
(win_pct hard-clamped to [35, 65], "a read, not a prediction"); the pool
ranking orders the caller's own champions as options, never players.
"""
from __future__ import annotations

import re

from app import draftintel

# permalink shape: "266.64.0.0.0-121.0.0.0.0" (ally ids - enemy ids, 0 = empty)
_STATE_RE = re.compile(r"^\d{1,6}(\.\d{1,6}){4}-\d{1,6}(\.\d{1,6}){4}$")
SLOTS = 5


def clean_names(value, cap: int = SLOTS) -> list[str]:
    """Defensive request-body sanitizer: a list of strings, capped."""
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str)][:cap]


def _picks(names: list[str]) -> list[dict]:
    return [p for p in (draftintel.profile_by_name(n) for n in names) if p]


def _chips(summary: dict) -> dict:
    """The at-a-glance structure chips a draft board shows per side."""
    return {
        "ad": summary["physical_threats"],
        "ap": summary["magic_threats"],
        "mixed": summary["mixed_threats"],
        "frontline": summary["frontline"],
        "heavy_cc": summary["heavy_cc_count"],
    }


def analyze(ally: list[str], enemy: list[str]) -> dict:
    """One engine pass over the current board. Unknown names are dropped
    silently (a half-typed picker value must never 500 the live panel)."""
    ally_picks, enemy_picks = _picks(ally), _picks(enemy)
    ally_comp = draftintel.classify_comp(ally_picks)
    enemy_comp = draftintel.classify_comp(enemy_picks)
    ally_summary = draftintel.summarize_team(ally_picks)
    enemy_summary = draftintel.summarize_team(enemy_picks)
    balance = draftintel.draft_balance(ally_comp, enemy_comp,
                                       ally_summary, enemy_summary)
    return {
        "ally": [draftintel.identity(p["name"]) for p in ally_picks],
        "enemy": [draftintel.identity(p["name"]) for p in enemy_picks],
        "ally_comp": ally_comp,
        "enemy_comp": enemy_comp,
        "ally_chips": _chips(ally_summary),
        "enemy_chips": _chips(enemy_summary),
        "balance": balance,
        "hidden_enemies": SLOTS - len(enemy_picks),
    }


def rank_pool(pool: list[str], ally: list[str], enemy: list[str]) -> list[dict]:
    """"Which of my picks is best here": fold each pool champion into the ally
    side and rank by the resulting balance. Champions already on the board are
    skipped; the list is options with reasons, never a single dictated pick."""
    board = {p["name"] for p in _picks(ally)} | {p["name"] for p in _picks(enemy)}
    ranked = []
    for name in pool:
        ident = draftintel.identity(name)
        if ident is None or ident["name"] in board:
            continue
        result = analyze([*ally, ident["name"]], enemy)
        ranked.append({
            **ident,
            "win_pct": result["balance"]["win_pct"],
            "label": result["balance"]["label"],
            "tone": result["balance"]["tone"],
            "drivers": result["balance"]["drivers"],
            "ally_archetype": result["ally_comp"]["label"],
        })
    ranked.sort(key=lambda r: (-r["win_pct"], r["name"]))
    return ranked


# -- permalink codec --------------------------------------------------------------
def encode_state(ally: list[str], enemy: list[str]) -> str:
    """Board → "a1.a2.a3.a4.a5-e1.e2.e3.e4.e5" champion-id string (0 = empty).
    Unknown names encode as empty so a stale link never breaks."""
    key_of = {c["name"]: c["key"] for c in draftintel.roster()}

    def side(names: list[str]) -> str:
        ids = []
        for name in names[:SLOTS]:
            ident = draftintel.identity(name)
            ids.append(key_of.get(ident["name"], "0") if ident else "0")
        ids += ["0"] * (SLOTS - len(ids))
        return ".".join(ids)

    return f"{side(ally)}-{side(enemy)}"


def decode_state(code: str) -> tuple[list[str], list[str]] | None:
    """Permalink string → (ally names, enemy names), empty/unknown ids skipped.
    None for anything that is not a well-formed state code."""
    if not code or not _STATE_RE.match(code):
        return None

    def side(part: str) -> list[str]:
        out = []
        for raw in part.split("."):
            prof = draftintel.profile_by_id(raw) if raw != "0" else None
            if prof:
                out.append(prof["name"])
        return out

    ally_part, enemy_part = code.split("-", 1)
    return side(ally_part), side(enemy_part)
