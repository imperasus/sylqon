"""Draft Gauntlet run engine — server-held state so scores stay honest.

A run is a fixed-length sequence of pool puzzles (comparable scores: every run
is out of the same maximum). The browser only ever receives the question; the
pick comes back here, gets graded against the stored payload and the verdict
goes out — the tiers never ship ahead of the answer, unlike the Daily page
where a Wordle-style client reveal is fine because nothing is ranked.

Framing (docs/WEB_DRAFT_TERV.md §6): points grade *puzzle answers* — a game
mechanic like a chess-site puzzle score — never player skill from match data.
Several answers can share a tier; a full-score run just means agreeing with
the engine's strongest reads.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import config, puzzles
from app.models import GymRun

POINTS = {"strong": 3, "solid": 1, "risky": 0}
MAX_POINTS_PER_PUZZLE = max(POINTS.values())
_NICK_KEEP = re.compile(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿŐőŰűäÄ _.\-]")


class GymError(Exception):
    """A rule violation the page shows as a friendly note (never a 500)."""


def run_length() -> int:
    return config.GYM_RUN_LENGTH


def max_score() -> int:
    return run_length() * MAX_POINTS_PER_PUZZLE


def start_run(session: Session) -> GymRun:
    ids = puzzles.draw_pool_ids(session, run_length())
    if len(ids) < run_length():
        raise GymError("the puzzle pool is still filling up — try again soon")
    run = GymRun(run_id=uuid.uuid4().hex, puzzle_ids=ids, answers=[], score=0)
    session.add(run)
    session.commit()
    return run


def get_run(session: Session, run_id: str | None) -> GymRun | None:
    if not run_id or not isinstance(run_id, str) or len(run_id) > 64:
        return None
    return session.get(GymRun, run_id)


def current_puzzle(session: Session, run: GymRun) -> dict | None:
    """The unanswered question's payload, or None when the run is complete."""
    idx = len(run.answers)
    if idx >= len(run.puzzle_ids):
        return None
    return puzzles.get_pool_puzzle(session, run.puzzle_ids[idx])


def answer(session: Session, run: GymRun, pick) -> dict:
    """Grade one pick against the current question. Sequential by design: the
    run advances exactly one question per call, so a replayed request can
    never double-score."""
    payload = current_puzzle(session, run)
    if payload is None:
        raise GymError("this run is already finished")
    candidates = payload["candidates"]
    if not isinstance(pick, int) or not 0 <= pick < len(candidates):
        raise GymError("pick one of the shown candidates")
    tier = candidates[pick]["tier"]
    points = POINTS[tier]
    run.answers = [*run.answers, {"pick": pick, "tier": tier, "points": points}]
    run.score += points
    if len(run.answers) >= len(run.puzzle_ids):
        run.finished_at = datetime.now(timezone.utc)
    session.commit()
    return {"payload": payload, "pick": pick, "tier": tier, "points": points,
            "done": run.finished_at is not None}


def save_nickname(session: Session, run: GymRun, nickname: str | None) -> str:
    """One nickname per run, only after the finish line — the leaderboard row."""
    if run.finished_at is None:
        raise GymError("finish the run first")
    if run.nickname:
        raise GymError("this run already has a name")
    nick = _NICK_KEEP.sub("", nickname or "").strip()[:16]
    if len(nick) < 2:
        raise GymError("pick a name of 2-16 letters/digits")
    run.nickname = nick
    session.commit()
    return nick


def leaderboard(session: Session, days: int | None = None,
                limit: int = 10) -> list[tuple[str, int]]:
    """(nickname, best score) rows, best-first — one row per name so a grinder
    can't fill the board alone."""
    query = (select(GymRun.nickname, func.max(GymRun.score))
             .where(GymRun.nickname.isnot(None), GymRun.finished_at.isnot(None)))
    if days is not None:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        query = query.where(GymRun.finished_at >= since)
    query = (query.group_by(GymRun.nickname)
             .order_by(func.max(GymRun.score).desc(), GymRun.nickname)
             .limit(limit))
    return [(nick, int(score)) for nick, score in session.execute(query).all()]


def emoji_summary(run: GymRun) -> str:
    squares = {"strong": "\U0001f7e9", "solid": "\U0001f7e8", "risky": "\U0001f7e5"}
    return "".join(squares.get(a["tier"], "⬜") for a in run.answers)
