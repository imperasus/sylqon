"""Parsed, participant-centric view over a Match-V5 timeline payload.

The raw payload is ``{frames: [{timestamp, events, participantFrames}], frameInterval}``.
Positions only exist at frame boundaries (1/min), so every position-based rule
uses the frame nearest to an event — the heuristics are written to tolerate
that resolution (the roadmap explicitly accepts the "good heuristic" ceiling).
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Death:
    timestamp_ms: int
    position: tuple[float, float] | None
    killer_id: int
    assisting_ids: tuple[int, ...]


class TimelineView:
    def __init__(self, payload: dict, participant_id: int, team_participant_ids: set[int]):
        self.pid = participant_id
        self.team_ids = team_participant_ids
        self.frames: list[dict] = payload.get("frames", [])
        self.frame_interval_ms: int = payload.get("frameInterval", 60000)
        self.events: list[dict] = [
            e for frame in self.frames for e in frame.get("events", [])
        ]

    # -- frames -------------------------------------------------------------

    def frame_at_minute(self, minute: int) -> dict | None:
        idx = round(minute * 60000 / self.frame_interval_ms)
        if 0 <= idx < len(self.frames):
            return self.frames[idx]
        return None

    def participant_frame(self, frame: dict, pid: int | None = None) -> dict | None:
        return frame.get("participantFrames", {}).get(str(pid or self.pid))

    def nearest_frame(self, timestamp_ms: int) -> dict | None:
        if not self.frames:
            return None
        idx = round(timestamp_ms / self.frame_interval_ms)
        return self.frames[max(0, min(idx, len(self.frames) - 1))]

    def cs_at_minute(self, minute: int) -> int | None:
        frame = self.frame_at_minute(minute)
        pf = self.participant_frame(frame) if frame else None
        if pf is None:
            return None
        return int(pf.get("minionsKilled", 0)) + int(pf.get("jungleMinionsKilled", 0))

    def positions_at(self, timestamp_ms: int) -> dict[int, tuple[float, float]]:
        """pid → (x, y) from the frame nearest the timestamp."""
        frame = self.nearest_frame(timestamp_ms)
        if frame is None:
            return {}
        out: dict[int, tuple[float, float]] = {}
        for pid_str, pf in frame.get("participantFrames", {}).items():
            pos = pf.get("position")
            if pos:
                out[int(pid_str)] = (float(pos["x"]), float(pos["y"]))
        return out

    def gold_series(self) -> list[tuple[int, int]]:
        """(timestamp_ms, currentGold) per frame for the participant."""
        out = []
        for frame in self.frames:
            pf = self.participant_frame(frame)
            if pf is not None:
                out.append((frame.get("timestamp", 0), int(pf.get("currentGold", 0))))
        return out

    # -- events -------------------------------------------------------------

    def deaths(self) -> list[Death]:
        out = []
        for e in self.events:
            if e.get("type") == "CHAMPION_KILL" and e.get("victimId") == self.pid:
                pos = e.get("position")
                out.append(
                    Death(
                        timestamp_ms=e.get("timestamp", 0),
                        position=(float(pos["x"]), float(pos["y"])) if pos else None,
                        killer_id=e.get("killerId", 0),
                        assisting_ids=tuple(e.get("assistingParticipantIds", []) or []),
                    )
                )
        return out

    def ward_events(self, team_only: bool = True) -> list[dict]:
        out = []
        for e in self.events:
            if e.get("type") != "WARD_PLACED":
                continue
            if e.get("wardType") == "UNDEFINED":
                continue
            creator = e.get("creatorId", 0)
            if team_only and creator not in self.team_ids:
                continue
            out.append(e)
        return out

    def item_purchases(self, pid: int | None = None) -> list[dict]:
        pid = pid or self.pid
        return [
            e
            for e in self.events
            if e.get("type") == "ITEM_PURCHASED" and e.get("participantId") == pid
        ]

    def elite_monster_kills(self) -> list[dict]:
        return [e for e in self.events if e.get("type") == "ELITE_MONSTER_KILL"]

    def building_kills(self) -> list[dict]:
        return [e for e in self.events if e.get("type") == "BUILDING_KILL"]

    def game_length_ms(self) -> int:
        return self.frames[-1].get("timestamp", 0) if self.frames else 0


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])
