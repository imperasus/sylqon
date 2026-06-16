"""Per-champion mission queue: load the pending AI missions the live engine
should serve, and top the queue back up after a game (the rolling top-up model).

This is the only place that turns the post-game match stats into freshly
generated missions. It composes a DB read/write with an Ollama call, so — like
``db.matches`` — it lives apart from the pure engine. Generation is best-effort:
if Ollama is down or returns junk, the queue is simply left as-is and the static
role catalog covers the next game.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from sylqon import config
from sylqon.ai.mission_prompt import compile_mission_prompt
from sylqon.db.schema import ChampionMission, MatchHistory
from sylqon.livegame.missions import Mission, mission_from_row, normalize_mission

log = logging.getLogger(__name__)


def _pending_query(session: Session, champion_id: int):
    return (session.query(ChampionMission)
            .filter_by(champion_id=champion_id, status="pending")
            .order_by(ChampionMission.created_at.asc()))


def count_pending(session: Session, champion_id: int) -> int:
    return _pending_query(session, champion_id).count()


def load_pending(session: Session, champion_id: int, role: str) -> list[Mission]:
    """The champion's still-pending AI missions as live ``Mission`` templates."""
    rows = _pending_query(session, champion_id).limit(8).all()
    return [mission_from_row(r, role) for r in rows]


def pending_texts(session: Session, champion_id: int) -> list[str]:
    return [r.text for r in _pending_query(session, champion_id).all()]


def latest_game(session: Session, champion_id: int) -> dict:
    """Shape the most recent stored game on the champion into the dict the
    mission prompt expects. Empty-ish when there is no history yet."""
    m = (session.query(MatchHistory)
         .filter_by(champion_id=champion_id)
         .order_by(MatchHistory.played_at.desc()).first())
    if m is None:
        return {"result": "?", "kda": {}, "stats": {}, "role": ""}
    return {"result": m.result or "?", "kda": m.kda_json or {},
            "stats": m.stats_json or {}, "role": m.role or ""}


def topup(session: Session, champion_id: int, champion: str, role: str,
          engine, *, target: int | None = None, game_session: str = "") -> int:
    """Generate enough fresh AI missions to bring the champion's pending queue up
    to ``target``. Returns the number of new missions inserted (0 if the queue is
    already full, Ollama is unavailable, or nothing validated)."""
    target = target or config.CHAMPION_MISSION_TARGET
    needed = target - count_pending(session, champion_id)
    if needed <= 0:
        return 0
    if engine is None or not engine.available():
        log.info("Mission top-up for %s skipped (Ollama unavailable)", champion)
        return 0

    last = latest_game(session, champion_id)
    prompt = compile_mission_prompt(champion, role, last, needed,
                                    pending_texts(session, champion_id))
    ai = engine.evaluate(prompt, options={"num_predict": 700})
    raw_missions = (ai or {}).get("missions") if isinstance(ai, dict) else None
    if not isinstance(raw_missions, list):
        log.info("Mission top-up for %s produced no usable missions", champion)
        return 0

    inserted = 0
    for raw in raw_missions:
        if inserted >= needed:
            break
        norm = normalize_mission(raw)
        if norm is None:
            continue
        session.add(ChampionMission(
            champion_id=champion_id, mission_type=norm["type"], params=norm["params"],
            reward_points=norm["reward_points"], text=norm["text"],
            source="ai", status="pending", game_session=game_session,
        ))
        inserted += 1
    session.flush()
    log.info("Mission top-up for %s: +%d AI mission(s)", champion, inserted)
    return inserted
