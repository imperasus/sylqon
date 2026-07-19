"""End-to-end advice pipeline over stored data: load match + timeline +
participant → run heuristics → select top-1 → render HU+EN → cache in the
``advice`` table (deterministic pipeline, so one row per match+player)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app import aggregate, store
from app.advice import benchmarks, messages
from app.advice.heuristics import PlayerContext, run_all
from app.advice.selector import select_top
from app.advice.timeline import TimelineView


def _tuning_with_own_benchmarks(session: Session, puuid: str | None = None) -> dict:
    """Threshold tuning + benchmark tables, with own-data aggregation overlaid
    on the seeds for every role that cleared the sample threshold. When the
    player's rank is known, their band's medians take precedence over ALL."""
    from app.models import PlayerRank

    band = None
    if puuid:
        rank = session.get(PlayerRank, puuid)
        if rank:
            band = aggregate.band_for_tier(rank.tier)
    tun = benchmarks.tuning()
    cs_over, vision_over = aggregate.load_effective_overrides(session, band=band)
    tun["cs_benchmarks"] = {**benchmarks.CS_BENCHMARKS, **cs_over}
    tun["vision_benchmarks"] = {**benchmarks.VISION_BENCHMARKS, **vision_over}
    return tun


class AdviceNotPossible(Exception):
    pass


def _as_response(
    match_id: str,
    puuid: str,
    champion: str,
    role: str,
    top_finding: dict,
    all_findings: list,
    text_hu: str,
    text_en: str,
    lang: str,
    cached: bool,
) -> dict:
    return {
        "match_id": match_id,
        "puuid": puuid,
        "champion": champion,
        "role": role,
        "top_finding": top_finding,
        "all_findings": all_findings,
        "text": text_hu if lang == "hu" else text_en,
        "text_hu": text_hu,
        "text_en": text_en,
        "lang": lang,
        "cached": cached,
    }


def generate_findings(session: Session, match_id: str, puuid: str):
    """Run the heuristics for one stored (match, player). Returns
    (participant, findings) — split out for tests and future batch jobs."""
    bundle = store.get_match_with_timeline(session, match_id)
    if bundle is None:
        raise AdviceNotPossible(f"match or timeline not stored: {match_id}")
    _, timeline = bundle
    participant = store.get_participant(session, match_id, puuid)
    if participant is None:
        raise AdviceNotPossible(f"player {puuid} not found in match {match_id}")

    raw_participants = bundle[0].raw.get("participants", [])
    team_ids = {
        p.get("participantId")
        for p in raw_participants
        if p.get("teamId") == participant.team_id
    }
    enemy_champions = tuple(
        p.get("championName", "")
        for p in raw_participants
        if p.get("teamId") not in (participant.team_id, None) and p.get("championName")
    )
    view = TimelineView(
        timeline.payload,
        participant_id=participant.participant_id,
        team_participant_ids=team_ids,
    )
    ctx = PlayerContext(
        participant_id=participant.participant_id,
        team_id=participant.team_id or 0,
        team_position=participant.team_position or "",
        champion_name=participant.champion_name or "?",
        deaths=participant.deaths or 0,
        kills=participant.kills or 0,
        assists=participant.assists or 0,
        wards_placed=participant.wards_placed or 0,
        control_wards_bought=participant.control_wards_bought or 0,
        enemy_champions=enemy_champions,
    )
    return participant, run_all(view, ctx, _tuning_with_own_benchmarks(session, puuid))


def get_or_generate_advice(
    session: Session, match_id: str, puuid: str, lang: str = "hu"
) -> dict:
    lang = lang if lang in ("hu", "en") else "hu"

    cached = store.get_cached_advice(session, match_id, puuid)
    if cached is not None:
        participant = store.get_participant(session, match_id, puuid)
        return _as_response(
            match_id,
            puuid,
            participant.champion_name if participant else "?",
            participant.team_position if participant else "",
            cached.top_finding,
            cached.all_findings,
            cached.text_hu,
            cached.text_en,
            lang,
            cached=True,
        )

    participant, findings = generate_findings(session, match_id, puuid)
    top = select_top(findings)
    champion = participant.champion_name or "?"
    text_hu = messages.render(top, "hu", champion)
    text_en = messages.render(top, "en", champion)
    top_dict = top.as_dict() if top else {"type": "none", "message_key": "clean_game"}
    all_dicts = [f.as_dict() for f in findings]

    store.save_advice(session, match_id, puuid, top_dict, all_dicts, text_hu, text_en)
    return _as_response(
        match_id,
        puuid,
        champion,
        participant.team_position or "",
        top_dict,
        all_dicts,
        text_hu,
        text_en,
        lang,
        cached=False,
    )
