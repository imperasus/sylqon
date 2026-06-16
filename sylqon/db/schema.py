"""SQLAlchemy ORM models for the Antigravity v2 store.

Design notes (these intentionally diverge from the idealized architecture doc to
match the *real* runtime schema):

- ``ChampionBuild.build_json`` stores the **whole** build dict exactly as the
  existing pipeline produces it (``starting_items / boots / core_items /
  situational_pool / items / keystone / primary_runes / secondary_style /
  secondary_runes / stat_shards / spell1 / spell2``). Keeping it intact means the
  existing converters (``cache.opgg.opgg_to_build``) and validators
  (``loadout.from_candidate`` / ``apply_ai_decision``) work unchanged.
- ``Champion.riot_key`` is Riot's numeric champion key (e.g. 103 for Ahri), used
  to map an LCU ``champion_id`` to a row. ``slug`` is the Data Dragon id
  ("Ahri", "MissFortune") used for icon URLs.
- Roles use the normalized ``top/jungle/middle/bottom/utility`` vocabulary
  (see ``data.static.ROLE_ALIASES``).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Champion(Base):
    __tablename__ = "champions"

    id = Column(Integer, primary_key=True)
    riot_key = Column(Integer, unique=True, index=True)  # 103
    name = Column(String, unique=True, nullable=False)   # "Ahri"
    slug = Column(String)                                 # "Ahri" (ddragon id)
    roles = Column(JSON, nullable=False, default=list)    # ["middle"]
    tags = Column(JSON, default=list)                     # ["Mage"]
    op_gg_stats = Column(JSON)                            # {tier, win_rate, pick_rate, ...}

    builds = relationship("ChampionBuild", back_populates="champion",
                          cascade="all, delete-orphan")


class ChampionBuild(Base):
    __tablename__ = "champion_builds"
    __table_args__ = (
        UniqueConstraint("champion_id", "role", name="uq_build_champ_role"),
        Index("ix_build_champ_role", "champion_id", "role"),
    )

    id = Column(Integer, primary_key=True)
    champion_id = Column(Integer, ForeignKey("champions.id"), nullable=False)
    role = Column(String, nullable=False)
    patch = Column(String)
    build_json = Column(JSON, nullable=False)  # the full real build dict
    win_rate = Column(Float)
    pick_rate = Column(Float)
    source = Column(String)                    # "opgg" | "opgg-live" | "seed" | ...
    updated_at = Column(DateTime, default=datetime.utcnow)

    champion = relationship("Champion", back_populates="builds")


class ChampionCounter(Base):
    __tablename__ = "champion_counters"
    __table_args__ = (
        Index("ix_counter_champ_role", "champion_id", "role"),
    )

    champion_id = Column(Integer, ForeignKey("champions.id"), primary_key=True)
    counter_id = Column(Integer, ForeignKey("champions.id"), primary_key=True)
    role = Column(String, primary_key=True)
    advantage_score = Column(Float)  # -10 (hard countered) .. +10 (hard counter)


class ChampionSynergy(Base):
    __tablename__ = "champion_synergies"
    __table_args__ = (
        Index("ix_synergy_champ_role", "champion_id", "role"),
    )

    champion_id = Column(Integer, ForeignKey("champions.id"), primary_key=True)
    synergy_id = Column(Integer, ForeignKey("champions.id"), primary_key=True)
    role = Column(String, primary_key=True)
    synergy_score = Column(Float)  # 0 .. 10


class ProBuild(Base):
    """A pro/esports player's build on a champion+role, captured via the op.gg
    MCP tools (Claude-driven, like the op.gg-build ingest). Display-only — it is
    never injected. ``build_json`` carries ``{items:[{id,name}], skill_order,
    spell1, spell2, keystone}`` so the UI can render it without extra lookups."""
    __tablename__ = "pro_builds"
    __table_args__ = (
        UniqueConstraint("champion_id", "role", "pro_name", name="uq_pro_build"),
        Index("ix_pro_build_champ_role", "champion_id", "role"),
    )

    id = Column(Integer, primary_key=True)
    champion_id = Column(Integer, ForeignKey("champions.id"), nullable=False)
    role = Column(String, nullable=False)
    pro_name = Column(String, nullable=False)   # "Faker"
    team = Column(String)                        # "T1"
    region = Column(String)                      # "LCK"
    patch = Column(String)
    result = Column(String)                      # "Win" | "Loss" (optional)
    build_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class PlayerProfile(Base):
    """Account-level progression for the in-game overlay coach. Single local
    profile (id=1), labelled with the connected summoner name. ``level`` is
    derived (``total_points // 100 + 1``); ``unlocked_badges`` is a JSON list of
    badge ids."""
    __tablename__ = "player_profiles"

    id = Column(Integer, primary_key=True)
    summoner_name = Column(String)
    total_points = Column(Integer, default=0)
    level = Column(Integer, default=1)
    unlocked_badges = Column(JSON, default=list)
    updated_at = Column(DateTime, default=datetime.utcnow)


class MissionRun(Base):
    """One resolved mission attempt (completed or failed). Only resolved runs are
    persisted (not every tick), so this table stays small."""
    __tablename__ = "mission_runs"
    __table_args__ = (
        Index("ix_mission_run_profile", "profile_id"),
    )

    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("player_profiles.id"), nullable=False)
    champion_id = Column(Integer, ForeignKey("champions.id"))  # which champ leveled
    game_session = Column(String)
    role = Column(String)
    mission_type = Column(String)
    params = Column(JSON)
    reward_points = Column(Integer)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, default=datetime.utcnow)
    result = Column(String)            # "completed" | "failed"
    points_awarded = Column(Integer, default=0)


class ChampionProgress(Base):
    """Per-champion mastery for the overlay coach. One row per champion the player
    has earned points on. ``level`` is derived (``total_points // 100 + 1``); the
    account-level ``PlayerProfile.total_points`` is the sum of these rows."""
    __tablename__ = "champion_progress"

    id = Column(Integer, primary_key=True)
    champion_id = Column(Integer, ForeignKey("champions.id"), unique=True, nullable=False)
    total_points = Column(Integer, default=0)
    level = Column(Integer, default=1)
    games_played = Column(Integer, default=0)
    badges = Column(JSON, default=list)
    updated_at = Column(DateTime, default=datetime.utcnow)


class ChampionMission(Base):
    """One AI-generated, champion-specific mission in the rolling per-champion
    queue. The live ``MissionEngine`` serves the ``pending`` rows for the champion
    being played (falling back to the static role catalog when the queue is empty),
    and tops the queue back up after each game on that champion. Every row is
    validated against ``livegame.missions`` evaluators before insert, so it is
    always machine-evaluable from the live snapshot."""
    __tablename__ = "champion_missions"
    __table_args__ = (
        Index("ix_champ_mission_pending", "champion_id", "status"),
    )

    id = Column(Integer, primary_key=True)
    champion_id = Column(Integer, ForeignKey("champions.id"), nullable=False)
    mission_type = Column(String, nullable=False)
    params = Column(JSON, nullable=False)
    reward_points = Column(Integer, nullable=False)
    text = Column(String, nullable=False)
    source = Column(String, default="ai")      # "ai" | "general"
    status = Column(String, default="pending")  # "pending" | "completed"
    game_session = Column(String)               # session it was generated from
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)


class MatchHistory(Base):
    __tablename__ = "match_history"
    __table_args__ = (
        Index("ix_match_played_at", "played_at"),
    )

    id = Column(Integer, primary_key=True)
    game_id = Column(String, unique=True, nullable=False)
    champion_id = Column(Integer, ForeignKey("champions.id"))
    role = Column(String)
    result = Column(String)            # "Win" | "Loss"
    kda_json = Column(JSON)            # {kills, deaths, assists}
    stats_json = Column(JSON)          # {gold, total_damage, vision_score, cs, ...}
    timeline_json = Column(JSON)       # key events
    played_at = Column(DateTime, nullable=False)

    analysis = relationship("MatchAnalysis", uselist=False, back_populates="match",
                            cascade="all, delete-orphan")


class MatchAnalysis(Base):
    __tablename__ = "match_analysis"

    id = Column(Integer, primary_key=True)
    match_id = Column(Integer, ForeignKey("match_history.id"), unique=True)
    summary = Column(String)
    strengths = Column(JSON)           # ["...", ...]
    weaknesses = Column(JSON)
    tips = Column(JSON)
    generated_at = Column(DateTime, default=datetime.utcnow)

    match = relationship("MatchHistory", back_populates="analysis")
