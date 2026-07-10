"""Meta-build aggregation — the op.gg replacement path (roadmap §3.3).

For a champion+role, aggregates a current build from our own stored matches
and emits it in the exact payload shape the local app's ``opgg_to_build``
converter already consumes (`sylqon/cache/opgg_fetch.py::_shape_payload`).
The local client can therefore switch data source without touching its
conversion or validation pipeline.

Sources per game (Summoner's Rift only, most recent games first):
- items: ITEM_PURCHASED timeline events → purchase order (starters, boots,
  core trio by earliest median position, situational pool by frequency)
- runes + stat shards: the participant's ``perks`` object (modal full pages)
- summoner spells: modal (D,F) pair, with the other seen spells as options
- skill order: SKILL_LEVEL_UP events → modal Q/W/E max order

Results are cached in the ``meta_builds`` table (recomputed when stale).
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.advice import benchmarks
from app.models import Match, MatchParticipant, MetaBuild, Timeline  # noqa: F401

log = logging.getLogger(__name__)

SR_QUEUES = {420, 440, 400, 430}
ROLE_MAP = {
    "top": "TOP", "jungle": "JUNGLE", "jng": "JUNGLE",
    "mid": "MIDDLE", "middle": "MIDDLE",
    "adc": "BOTTOM", "bot": "BOTTOM", "bottom": "BOTTOM",
    "support": "UTILITY", "sup": "UTILITY", "utility": "UTILITY",
}
MIN_GAMES = 8            # below this we return None → caller falls back to op.gg
MAX_GAMES = 60           # newest N games are plenty for a build
MIN_SITUATIONAL = 6      # the counter-pick pool the local AI chooses from
STALE_AFTER_HOURS = 24
_SKILL_KEYS = {1: "Q", 2: "W", 3: "E"}


def normalize_role(role: str) -> str | None:
    return ROLE_MAP.get((role or "").strip().lower())


def _purchases_for(timeline: dict, pid: int) -> list[int]:
    out = []
    for frame in timeline.get("frames", []):
        for e in frame.get("events", []):
            if e.get("type") == "ITEM_PURCHASED" and e.get("participantId") == pid:
                out.append((e.get("timestamp", 0), e.get("itemId")))
    return [iid for _, iid in sorted(out)]


def _skill_order_for(timeline: dict, pid: int) -> tuple[str, ...] | None:
    counts: Counter = Counter()
    order: list[str] = []
    for frame in timeline.get("frames", []):
        for e in frame.get("events", []):
            if (e.get("type") == "SKILL_LEVEL_UP" and e.get("participantId") == pid
                    and e.get("skillSlot") in _SKILL_KEYS):
                key = _SKILL_KEYS[e["skillSlot"]]
                counts[key] += 1
                if counts[key] == 5 and key not in order:
                    order.append(key)
    if len(order) < 3:
        for key, _ in counts.most_common():
            if key not in order:
                order.append(key)
    return tuple(order[:3]) if len(order) == 3 else None


def _modal(counter: Counter):
    return counter.most_common(1)[0][0] if counter else None


def _role_item_pool(session: Session, role: str, limit: int = 1500) -> list[int]:
    """Most-common completed items across the role's recent participants
    (final inventories — no timeline reads needed). Pads thin situational pools."""
    rows = session.execute(
        select(MatchParticipant.stats)
        .join(Match, Match.match_id == MatchParticipant.match_id)
        .where(MatchParticipant.team_position == role)
        .where(Match.queue_id.in_(SR_QUEUES))
        .order_by(Match.game_creation.desc())
        .limit(limit)
    )
    counts: Counter = Counter()
    for (stats,) in rows:
        for slot in range(6):
            iid = (stats or {}).get(f"item{slot}")
            if iid in benchmarks.CORE_ITEM_IDS:
                counts[iid] += 1
    return [iid for iid, _ in counts.most_common(20)]


def compute_meta_build(session: Session, champion: str, role: str) -> dict | None:
    """Aggregate the op.gg-shaped build payload, or None below MIN_GAMES."""
    rows = list(
        session.execute(
            select(MatchParticipant, Match)
            .join(Match, Match.match_id == MatchParticipant.match_id)
            .where(MatchParticipant.champion_name.ilike(champion))
            .where(MatchParticipant.team_position == role)
            .where(Match.queue_id.in_(SR_QUEUES))
            .order_by(Match.game_creation.desc())
            .limit(MAX_GAMES)
        )
    )
    if len(rows) < MIN_GAMES:
        return None

    timelines = {
        t.match_id: t.payload
        for t in session.execute(
            select(Timeline).where(Timeline.match_id.in_([m.match_id for _, m in rows]))
        ).scalars()
    }

    starters: Counter = Counter()
    boots: Counter = Counter()
    core_seen: Counter = Counter()
    core_positions: dict[int, list[int]] = defaultdict(list)
    spells: Counter = Counter()
    spell_pool: Counter = Counter()
    primary_pages: Counter = Counter()
    secondary_pages: Counter = Counter()
    shard_tuples: Counter = Counter()
    skill_orders: Counter = Counter()
    wins = 0

    for participant, match in rows:
        wins += 1 if participant.win else 0
        stats = participant.stats or {}

        s1, s2 = stats.get("summoner1Id"), stats.get("summoner2Id")
        if s1 and s2:
            spells[(s1, s2)] += 1
            spell_pool[s1] += 1
            spell_pool[s2] += 1

        perks = stats.get("perks") or {}
        styles = perks.get("styles") or []
        if len(styles) == 2:
            prim = tuple(sel.get("perk") for sel in styles[0].get("selections", []))
            sec = tuple(sel.get("perk") for sel in styles[1].get("selections", []))
            if len(prim) == 4 and len(sec) == 2:
                primary_pages[(styles[0].get("style"), prim)] += 1
                secondary_pages[(styles[1].get("style"), sec)] += 1
        stat_perks = perks.get("statPerks") or {}
        shard = (stat_perks.get("offense"), stat_perks.get("flex"), stat_perks.get("defense"))
        if all(shard):
            shard_tuples[shard] += 1

        timeline = timelines.get(match.match_id)
        if not timeline:
            continue
        purchases = _purchases_for(timeline, participant.participant_id)
        completed_seen: list[int] = []
        for iid in purchases:
            if iid in benchmarks.BOOT_IDS:
                boots[iid] += 1
            elif iid in benchmarks.CORE_ITEM_IDS and iid not in completed_seen:
                completed_seen.append(iid)
        for pos, iid in enumerate(completed_seen):
            core_seen[iid] += 1
            core_positions[iid].append(pos)
        start_set = tuple(sorted({
            iid for iid in purchases[:4] if iid in benchmarks.STARTER_IDS
        }))
        if start_set:
            starters[start_set] += 1

        so = _skill_order_for(timeline, participant.participant_id)
        if so:
            skill_orders[so] += 1

    games = len(rows)

    # Core trio: the most frequent completed items, ordered by their median
    # purchase position (earliest first).
    frequent = [iid for iid, n in core_seen.most_common() if n >= max(2, games * 0.2)]
    core_sorted = sorted(frequent, key=lambda iid: (median(core_positions[iid]), -core_seen[iid]))
    core_ids = core_sorted[:3]
    situational = [iid for iid in core_sorted[3:] if iid not in core_ids][:6]

    # The situational pool is what the local AI counter-picks FROM (it may not
    # invent items) — a thin pool starves it. Pad below MIN_SITUATIONAL: first
    # with the champion's own rarer completed items, then with the role's
    # most-common completed items across the whole dataset.
    if len(situational) < MIN_SITUATIONAL:
        used = set(core_ids) | set(situational)
        for iid, _ in core_seen.most_common():
            if len(situational) >= MIN_SITUATIONAL:
                break
            if iid not in used:
                situational.append(iid)
                used.add(iid)
        if len(situational) < MIN_SITUATIONAL:
            for iid in _role_item_pool(session, role):
                if len(situational) >= MIN_SITUATIONAL:
                    break
                if iid not in used:
                    situational.append(iid)
                    used.add(iid)

    spell_pair = _modal(spells) or (4, 7)
    primary_style, primary_runes = _modal(primary_pages) or (0, ())
    secondary_style, secondary_runes = _modal(secondary_pages) or (0, ())
    shards = _modal(shard_tuples) or ()
    skill = _modal(skill_orders)

    return {
        "champion": rows[0][0].champion_name,
        "role": role,
        "games": games,
        "win_rate": round(wins / games, 3),
        "source_patch": benchmarks.CORE_ITEMS_PATCH,
        "starter_item_ids": list(_modal(starters) or ()),
        "boot_ids": [iid for iid, _ in boots.most_common(3)],
        "core_item_ids": core_ids,
        "fourth_item_ids": situational[:2],
        "fifth_item_ids": situational[2:4],
        "sixth_item_ids": situational[4:6],
        "primary_page_id": primary_style,
        "primary_rune_ids": list(primary_runes),
        "secondary_page_id": secondary_style,
        "secondary_rune_ids": list(secondary_runes),
        "stat_mod_ids": list(shards),
        "summoner_spell_ids": list(spell_pair),
        "summoner_spell_options": [sid for sid, _ in spell_pool.most_common(6)],
        "skill_order": list(skill) if skill else [],
    }


def get_meta_build(session: Session, champion: str, role_raw: str) -> dict | None:
    """Cached lookup: recompute when missing or older than STALE_AFTER_HOURS."""
    role = normalize_role(role_raw)
    if role is None:
        return None
    row = session.get(MetaBuild, (champion.lower(), role))
    now = datetime.now(timezone.utc)
    if row is not None:
        computed = row.computed_at
        if computed.tzinfo is None:
            computed = computed.replace(tzinfo=timezone.utc)
        if now - computed < timedelta(hours=STALE_AFTER_HOURS):
            return row.payload
    payload = compute_meta_build(session, champion, role)
    if payload is None:
        return None
    row = row or MetaBuild(champion=champion.lower(), role=role)
    row.payload = payload
    row.samples = payload["games"]
    row.computed_at = now
    session.merge(row)
    session.commit()
    log.info("meta build computed: %s %s (%d games)", champion, role, payload["games"])
    return payload
