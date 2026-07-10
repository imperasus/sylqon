"""Coaching insights for the public profile — W4 of the web plan.

Two ingredients, both ToS-framed as coaching / descriptive display (never a
skill rating):

- **Descriptive aggregates** over the player's recent stored matches (win rate,
  KDA, CS/min, vision, recent form, most-played champions) — plain averages of
  the player's own official match data.
- **One coaching lesson** from the newest stored match that the advice pipeline
  can analyse (deterministic heuristics + cached per match).

Every slice degrades gracefully: no stored matches → None; advice unavailable
(e.g. timeline missing) → the aggregates still render without a lesson.
"""
from __future__ import annotations

import logging
from collections import Counter

from sqlalchemy.orm import Session

from app import matches

log = logging.getLogger(__name__)

RECENT_FORM_GAMES = 5
TOP_CHAMPS = 3
ADVICE_TRIES = 3  # newest matches to attempt a lesson on before giving up


def _avg(values: list, digits: int = 1) -> float | None:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), digits) if vals else None


def _latest_lesson(session: Session, rows: list[dict], puuid: str, lang: str) -> dict | None:
    from app.advice.pipeline import AdviceNotPossible, get_or_generate_advice

    for r in rows[:ADVICE_TRIES]:
        try:
            advice = get_or_generate_advice(session, r["match_id"], puuid, lang=lang)
        except AdviceNotPossible:
            continue
        except Exception as exc:  # advice must never break the profile page
            log.warning("advice failed for %s: %s", r["match_id"], exc)
            continue
        return {
            "match_id": r["match_id"],
            "champion": advice.get("champion"),
            "text": advice.get("text"),
        }
    return None


def build_insights(session: Session, puuid: str, limit: int = 20,
                   lang: str = "en") -> dict | None:
    """Aggregate the player's recent stored matches into an insights DTO, or
    None when nothing is stored yet."""
    rows = matches.list_for_puuid(session, puuid, limit=limit)
    if not rows:
        return None

    games = len(rows)
    wins = sum(1 for r in rows if r["win"])
    kills = sum(r["kills"] or 0 for r in rows)
    deaths = sum(r["deaths"] or 0 for r in rows)
    assists = sum(r["assists"] or 0 for r in rows)

    recent = rows[:RECENT_FORM_GAMES]
    champ_counter = Counter(r["champion"] for r in rows if r["champion"])
    top_champs = []
    for name, played in champ_counter.most_common(TOP_CHAMPS):
        champ_wins = sum(1 for r in rows if r["champion"] == name and r["win"])
        top_champs.append({"champion": name, "games": played, "wins": champ_wins})

    return {
        "games": games,
        "wins": wins,
        "winrate": round(wins / games * 100),
        "kda": round((kills + assists) / max(1, deaths), 2),
        "avg_cs_per_min": _avg([r["cs_per_min"] for r in rows]),
        "avg_vision": _avg([r["vision"] for r in rows]),
        "recent_form": {"games": len(recent),
                        "wins": sum(1 for r in recent if r["win"])},
        "top_champions": top_champs,
        "lesson": _latest_lesson(session, rows, puuid, lang),
    }
