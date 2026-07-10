"""SQLAlchemy models: matches, match_participants, timelines, advice.

Typed columns cover what the advice heuristics query or aggregate on; the full
Riot payloads are kept verbatim in JSON columns (JSONB on Postgres) so later
heuristics never need a re-crawl. Portable across Postgres and SQLite so the
store layer is unit-testable offline.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JsonCol = JSON().with_variant(JSONB(), "postgresql")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Match(Base):
    __tablename__ = "matches"

    match_id: Mapped[str] = mapped_column(Text, primary_key=True)  # "EUN1_123..."
    platform: Mapped[str] = mapped_column(Text)  # parsed from the match_id prefix
    region: Mapped[str] = mapped_column(Text)  # routing cluster used ("europe")
    queue_id: Mapped[int | None] = mapped_column(Integer)
    game_creation: Mapped[int | None] = mapped_column(BigInteger)  # epoch ms
    game_duration: Mapped[int | None] = mapped_column(Integer)  # seconds
    game_version: Mapped[str | None] = mapped_column(Text)
    patch: Mapped[str | None] = mapped_column(Text)  # "15.13" — benchmark bucketing
    raw: Mapped[dict] = mapped_column(JsonCol)  # full match "info" payload
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (Index("ix_matches_queue_patch", "queue_id", "patch"),)


class MatchParticipant(Base):
    __tablename__ = "match_participants"

    match_id: Mapped[str] = mapped_column(
        ForeignKey("matches.match_id", ondelete="CASCADE"), primary_key=True
    )
    puuid: Mapped[str] = mapped_column(Text, primary_key=True)
    participant_id: Mapped[int] = mapped_column(Integer)  # 1..10, joins timeline frames
    team_id: Mapped[int | None] = mapped_column(Integer)
    champion_id: Mapped[int | None] = mapped_column(Integer)
    champion_name: Mapped[str | None] = mapped_column(Text)
    team_position: Mapped[str | None] = mapped_column(Text)  # TOP/JUNGLE/MIDDLE/BOTTOM/UTILITY
    win: Mapped[bool | None] = mapped_column(Boolean)
    kills: Mapped[int | None] = mapped_column(Integer)
    deaths: Mapped[int | None] = mapped_column(Integer)
    assists: Mapped[int | None] = mapped_column(Integer)
    gold_earned: Mapped[int | None] = mapped_column(Integer)
    total_minions_killed: Mapped[int | None] = mapped_column(Integer)
    neutral_minions_killed: Mapped[int | None] = mapped_column(Integer)
    vision_score: Mapped[int | None] = mapped_column(Integer)
    wards_placed: Mapped[int | None] = mapped_column(Integer)
    control_wards_bought: Mapped[int | None] = mapped_column(Integer)
    damage_to_champions: Mapped[int | None] = mapped_column(Integer)
    stats: Mapped[dict] = mapped_column(JsonCol)  # full participant object

    __table_args__ = (
        Index("ix_participants_puuid", "puuid"),
        Index("ix_participants_champ_role", "champion_id", "team_position"),
    )


class Timeline(Base):
    __tablename__ = "timelines"

    match_id: Mapped[str] = mapped_column(
        ForeignKey("matches.match_id", ondelete="CASCADE"), primary_key=True
    )
    payload: Mapped[dict] = mapped_column(JsonCol)  # frames + events
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Advice(Base):
    __tablename__ = "advice"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(
        ForeignKey("matches.match_id", ondelete="CASCADE")
    )
    puuid: Mapped[str] = mapped_column(Text)
    top_finding: Mapped[dict] = mapped_column(JsonCol)
    all_findings: Mapped[list] = mapped_column(JsonCol)
    text_hu: Mapped[str] = mapped_column(Text)
    text_en: Mapped[str] = mapped_column(Text)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Deterministic pipeline → one advice row per (match, player); reruns reuse it.
    __table_args__ = (UniqueConstraint("match_id", "puuid", name="uq_advice_match_puuid"),)


class ComputedBenchmark(Base):
    """Role×rank-band benchmark medians aggregated from our own stored matches
    — the replacement path for the seed tables in advice/benchmarks.py. Band
    "ALL" always exists; rank bands appear as player_ranks coverage grows.
    Applied only once the sample count clears BENCHMARK_MIN_SAMPLES."""

    __tablename__ = "computed_benchmarks"

    role: Mapped[str] = mapped_column(Text, primary_key=True)
    band: Mapped[str] = mapped_column(Text, primary_key=True, default="ALL")
    data: Mapped[dict] = mapped_column(JsonCol)  # {cs10, cs15, wards_per_min, control_wards}
    samples: Mapped[int] = mapped_column(Integer)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class PlayerRank(Base):
    """Latest known solo-queue rank per PUUID (League-V4), fetched during the
    seed crawl — partitions the benchmark aggregation into rank bands."""

    __tablename__ = "player_ranks"

    puuid: Mapped[str] = mapped_column(Text, primary_key=True)
    platform: Mapped[str] = mapped_column(Text)
    tier: Mapped[str] = mapped_column(Text)  # IRON..CHALLENGER or UNRANKED
    division: Mapped[str | None] = mapped_column(Text)
    league_points: Mapped[int | None] = mapped_column(Integer)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class MetaBuild(Base):
    """Cached op.gg-shaped build payload per champion+role, aggregated from our
    own matches — the data source that replaces op.gg for the local client."""

    __tablename__ = "meta_builds"

    champion: Mapped[str] = mapped_column(Text, primary_key=True)  # lowercase
    role: Mapped[str] = mapped_column(Text, primary_key=True)  # TOP..UTILITY
    payload: Mapped[dict] = mapped_column(JsonCol)
    samples: Mapped[int] = mapped_column(Integer)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class LeaderboardSnapshot(Base):
    """Cached apex-league ladder (League-V4 challenger/grandmaster/master) per
    queue+platform+tier. Refreshed on a TTL — apex ladders move slowly, and one
    snapshot serves every visitor. Official public Riot ladder data."""

    __tablename__ = "leaderboard_snapshots"

    queue: Mapped[str] = mapped_column(Text, primary_key=True)  # RANKED_SOLO_5x5 / RANKED_FLEX_SR
    platform: Mapped[str] = mapped_column(Text, primary_key=True)  # euw1, na1, …
    tier: Mapped[str] = mapped_column(Text, primary_key=True)  # CHALLENGER/GRANDMASTER/MASTER
    payload: Mapped[dict] = mapped_column(JsonCol)  # shaped, LP-ranked rows
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ResolvedRiotId(Base):
    """puuid → Riot ID cache for leaderboard display. League-V4 apex entries
    carry only a puuid (no summoner name/id), so names come from Account-V1;
    resolved ids are kept permanently and the ladder fills in progressively —
    a rename just re-resolves if the entry ever goes cold."""

    __tablename__ = "resolved_riot_ids"

    puuid: Mapped[str] = mapped_column(Text, primary_key=True)
    platform: Mapped[str] = mapped_column(Text)
    riot_id: Mapped[str] = mapped_column(Text)  # "Name#TAG"
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class CrawlTarget(Base):
    """PUUIDs discovered from stored matches' co-players — the seed-crawl
    frontier. last_crawled_at=None → never crawled yet."""

    __tablename__ = "crawl_targets"

    puuid: Mapped[str] = mapped_column(Text, primary_key=True)
    source: Mapped[str] = mapped_column(Text, default="co-player")
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_crawled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LinkedAccount(Base):
    """Discord user ↔ Riot PUUID link (Riot-ID-based fallback linking; RSO
    OAuth replaces the verification story later, roadmap §4.1)."""

    __tablename__ = "linked_accounts"

    discord_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    puuid: Mapped[str] = mapped_column(Text, unique=True)
    game_name: Mapped[str] = mapped_column(Text)
    tag_line: Mapped[str] = mapped_column(Text)
    lang: Mapped[str] = mapped_column(Text, default="hu")
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class GuildConfig(Base):
    """Per-guild bot settings (advice channel + language)."""

    __tablename__ = "guild_configs"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    advice_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    reports_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    last_weekly_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lang: Mapped[str] = mapped_column(Text, default="hu")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AdviceFeedback(Base):
    """👍/👎 votes on delivered advice — the roadmap's advice_log seed, the
    future training signal for the ML death-audit swap (S7)."""

    __tablename__ = "advice_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(Text)
    puuid: Mapped[str] = mapped_column(Text)
    discord_user_id: Mapped[int] = mapped_column(BigInteger)
    vote: Mapped[int] = mapped_column(Integer)  # +1 / -1
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        UniqueConstraint("match_id", "puuid", "discord_user_id", name="uq_feedback_once"),
    )


class Delivery(Base):
    """One row per advice actually pushed to a channel (or baselined on watcher
    startup) — the dedupe guard that keeps the watcher from re-posting."""

    __tablename__ = "deliveries"

    match_id: Mapped[str] = mapped_column(
        ForeignKey("matches.match_id", ondelete="CASCADE"), primary_key=True
    )
    puuid: Mapped[str] = mapped_column(Text, primary_key=True)
    channel: Mapped[str] = mapped_column(Text)  # "discord" | "baseline"
    delivered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
