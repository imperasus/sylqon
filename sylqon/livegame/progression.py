"""Account-level progression: award points for completed missions, derive level,
and unlock simple threshold badges.

Stateless service (each method takes an explicit ``session``, matching
``mcp.ingest``). Single local profile (id=1). ``level = total_points // 100 + 1``.
Badges are recomputed from aggregate ``MissionRun`` counts on every resolution —
cheap given ≤2 concurrent missions.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from sylqon.db.schema import (
    ChampionMission,
    ChampionProgress,
    MissionRun,
    PlayerProfile,
)
from sylqon.livegame.missions import NO_DEATH, OBJECTIVE, WARDING

PROFILE_ID = 1

# badge id -> human label. Thresholds evaluated in ``_evaluate_badges``.
BADGES = {
    "first_mission": "First mission complete",
    "deathless_10": "10 no-death missions",
    "objective_5": "5 objectives secured",
    "ward_warden_10": "10 warding missions",
    "level_5": "Reached level 5",
}


class ProgressionService:
    # -- profile -------------------------------------------------------------
    def ensure_profile(self, session: Session, summoner_name: str = "") -> PlayerProfile:
        profile = session.get(PlayerProfile, PROFILE_ID)
        if profile is None:
            profile = PlayerProfile(id=PROFILE_ID, summoner_name=summoner_name or "",
                                    total_points=0, level=1, unlocked_badges=[])
            session.add(profile)
            session.flush()
        elif summoner_name and profile.summoner_name != summoner_name:
            profile.summoner_name = summoner_name
        return profile

    def get_profile(self, session: Session) -> PlayerProfile | None:
        return session.get(PlayerProfile, PROFILE_ID)

    # -- champion mastery ----------------------------------------------------
    def ensure_champion_progress(self, session: Session, champion_id: int) -> ChampionProgress:
        cp = (session.query(ChampionProgress)
              .filter_by(champion_id=champion_id).first())
        if cp is None:
            cp = ChampionProgress(champion_id=champion_id, total_points=0, level=1,
                                  games_played=0, badges=[])
            session.add(cp)
            session.flush()
        return cp

    def champion_progress(self, session: Session, champion_id: int) -> ChampionProgress | None:
        return (session.query(ChampionProgress)
                .filter_by(champion_id=champion_id).first())

    def bump_games_played(self, session: Session, champion_id: int) -> None:
        cp = self.ensure_champion_progress(session, champion_id)
        cp.games_played = (cp.games_played or 0) + 1
        cp.updated_at = datetime.utcnow()
        session.flush()

    # -- resolution ----------------------------------------------------------
    def record_resolution(self, session: Session, profile: PlayerProfile, mission,
                          result: str, *, champion_id: int | None = None,
                          game_session: str = "") -> MissionRun:
        """Persist a resolved mission; award points + recompute level/badges on
        completion. ``mission`` is a ``missions.Mission``. When ``champion_id`` is
        given the points also accrue to that champion's mastery (the account total
        equals the sum of champion points, since every live completion is credited
        to the champion being played). A queue-backed mission (id ``cm:<n>``) flips
        its ``ChampionMission`` row to completed."""
        points = mission.reward_points if result == "completed" else 0
        run = MissionRun(
            profile_id=profile.id, champion_id=champion_id, game_session=game_session,
            role=mission.role, mission_type=mission.type, params=dict(mission.params),
            reward_points=mission.reward_points, finished_at=datetime.utcnow(),
            result=result, points_awarded=points,
        )
        session.add(run)

        if result == "completed":
            profile.total_points = (profile.total_points or 0) + points
            profile.level = profile.total_points // 100 + 1
            if champion_id is not None:
                cp = self.ensure_champion_progress(session, champion_id)
                cp.total_points = (cp.total_points or 0) + points
                cp.level = cp.total_points // 100 + 1
                cp.updated_at = datetime.utcnow()
            self._complete_queue_row(session, mission.id)

        session.flush()  # so the badge counts include this run
        profile.unlocked_badges = self._evaluate_badges(session, profile)
        profile.updated_at = datetime.utcnow()
        session.flush()
        return run

    @staticmethod
    def _complete_queue_row(session: Session, mission_id: str) -> None:
        """Flip the exact ``ChampionMission`` row backing a resolved AI mission
        (id tagged ``cm:<row id>``) so it isn't re-served and the queue tops up."""
        if not isinstance(mission_id, str) or not mission_id.startswith("cm:"):
            return
        try:
            row_id = int(mission_id.split(":", 1)[1])
        except (ValueError, IndexError):
            return
        row = session.get(ChampionMission, row_id)
        if row is not None and row.status != "completed":
            row.status = "completed"
            row.completed_at = datetime.utcnow()

    # -- badges --------------------------------------------------------------
    def _counts(self, session: Session, profile: PlayerProfile) -> dict:
        rows = (session.query(MissionRun.mission_type, func.count())
                .filter(MissionRun.profile_id == profile.id,
                        MissionRun.result == "completed")
                .group_by(MissionRun.mission_type).all())
        by_type = {t: c for t, c in rows}
        return {"completed": sum(by_type.values()), "by_type": by_type,
                "level": profile.level or 1}

    def _evaluate_badges(self, session: Session, profile: PlayerProfile) -> list[str]:
        c = self._counts(session, profile)
        bt = c["by_type"]
        out: list[str] = []
        if c["completed"] >= 1:
            out.append("first_mission")
        if bt.get(NO_DEATH, 0) >= 10:
            out.append("deathless_10")
        if bt.get(OBJECTIVE, 0) >= 5:
            out.append("objective_5")
        if bt.get(WARDING, 0) >= 10:
            out.append("ward_warden_10")
        if c["level"] >= 5:
            out.append("level_5")
        return out

    # -- serialization + reset ----------------------------------------------
    def serialize_profile(self, profile: PlayerProfile) -> dict:
        badges = [{"id": b, "label": BADGES.get(b, b)}
                  for b in (profile.unlocked_badges or [])]
        return {
            "summoner_name": profile.summoner_name or "",
            "total_points": profile.total_points or 0,
            "level": profile.level or 1,
            "badges": badges,
        }

    @staticmethod
    def serialize_champion_progress(cp: ChampionProgress | None, champion: str = "") -> dict | None:
        if cp is None:
            return None
        pts = cp.total_points or 0
        return {
            "champion": champion,
            "level": cp.level or 1,
            "total_points": pts,
            "points_into_level": pts % 100,
            "games_played": cp.games_played or 0,
        }

    def reset(self, session: Session) -> None:
        session.query(MissionRun).delete()
        session.query(ChampionMission).delete()
        session.query(ChampionProgress).delete()
        profile = session.get(PlayerProfile, PROFILE_ID)
        if profile is not None:
            profile.total_points = 0
            profile.level = 1
            profile.unlocked_badges = []
            profile.updated_at = datetime.utcnow()
        session.flush()
