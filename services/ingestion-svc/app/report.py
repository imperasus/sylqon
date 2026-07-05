"""Weekly trend report — the core of the roadmap's S2 premium tier ("heti
összefoglaló, trend-riport"), webhook edition.

Aggregates a player's stored matches over a window: form, KDA, CS@10 vs the
active benchmark, vision, top champions, and the most recurring lesson across
the window (findings recomputed deterministically per match).
"""
from __future__ import annotations

import logging
import time
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.advice.pipeline import AdviceNotPossible, generate_findings, _tuning_with_own_benchmarks
from app.models import Match, MatchParticipant

log = logging.getLogger(__name__)

_FINDING_LABELS = {
    "death_context": {"hu": "pozicionálás / halálok", "en": "positioning / deaths"},
    "cs_benchmark": {"hu": "farmolás (CS)", "en": "farming (CS)"},
    "item_timing": {"hu": "item-időzítés", "en": "item timing"},
    "vision": {"hu": "vízió", "en": "vision"},
    "objective_presence": {"hu": "objective-jelenlét", "en": "objective presence"},
}


def build_report(session: Session, puuid: str, days: int = 7) -> dict | None:
    """Returns the aggregated report dict, or None when the window is empty."""
    since_ms = int((time.time() - days * 86400) * 1000)
    rows = list(
        session.execute(
            select(MatchParticipant, Match)
            .join(Match, Match.match_id == MatchParticipant.match_id)
            .where(MatchParticipant.puuid == puuid)
            .where(Match.game_creation >= since_ms)
            .order_by(Match.game_creation)
        )
    )
    if not rows:
        return None

    tun = _tuning_with_own_benchmarks(session)
    cs_table = tun["cs_benchmarks"]

    wins = 0
    kills = deaths = assists = 0
    wards = 0.0
    minutes = 0.0
    cs10_deltas: list[float] = []
    champs: Counter = Counter()
    champ_wins: Counter = Counter()
    finding_types: Counter = Counter()
    form = []

    for participant, match in rows:
        win = bool(participant.win)
        wins += win
        form.append("W" if win else "L")
        kills += participant.kills or 0
        deaths += participant.deaths or 0
        assists += participant.assists or 0
        wards += participant.wards_placed or 0
        minutes += (match.game_duration or 0) / 60
        champs[participant.champion_name] += 1
        champ_wins[participant.champion_name] += win

        try:
            _, findings = generate_findings(session, match.match_id, puuid)
        except AdviceNotPossible:
            findings = []
        for f in findings:
            finding_types[f.type] += 1
            if f.type == "cs_benchmark" and "cs10" in f.evidence:
                cs10_deltas.append(f.evidence["cs10"] - f.evidence["bench10"])

    games = len(rows)
    top_champs = [
        {"name": name, "games": n, "wins": champ_wins[name]}
        for name, n in champs.most_common(3)
    ]
    focus_type = finding_types.most_common(1)[0][0] if finding_types else None
    role = rows[-1][0].team_position or ""
    bench10 = (cs_table.get(role) or {}).get(10)

    return {
        "puuid": puuid,
        "days": days,
        "games": games,
        "wins": wins,
        "losses": games - wins,
        "winrate_pct": round(wins / games * 100),
        "form": "".join(form[-10:]),
        "avg_kda": round((kills + assists) / max(1, deaths), 2),
        "kda_line": f"{round(kills / games, 1)}/{round(deaths / games, 1)}/{round(assists / games, 1)}",
        "wards_per_min": round(wards / minutes, 2) if minutes else 0.0,
        "cs10_delta_avg": round(sum(cs10_deltas) / len(cs10_deltas), 1) if cs10_deltas else None,
        "cs10_bench": bench10,
        "top_champs": top_champs,
        "focus_type": focus_type,
        "focus_counts": dict(finding_types),
    }


def render_text(report: dict, lang: str) -> str:
    champs = ", ".join(
        f"{c['name']} ({c['wins']}/{c['games']})" for c in report["top_champs"]
    )
    focus = _FINDING_LABELS.get(report["focus_type"], {}).get(lang) if report["focus_type"] else None
    if lang == "hu":
        lines = [
            f"**{report['games']} meccs** az elmúlt {report['days']} napban — "
            f"{report['wins']}W/{report['losses']}L ({report['winrate_pct']}%), forma: `{report['form']}`",
            f"Átlag KDA: **{report['kda_line']}** ({report['avg_kda']}) · vízió: {report['wards_per_min']} ward/perc",
            f"Legtöbbet játszott: {champs}",
        ]
        if report["cs10_delta_avg"] is not None:
            lines.append(
                f"CS@10 a benchmarkhoz képest átlagosan **{report['cs10_delta_avg']:+.1f}** "
                f"(cél: {report['cs10_bench']})"
            )
        if focus:
            lines.append(f"🎯 A hét fókusza: **{focus}** — ez volt a leggyakoribb tanulság.")
        return "\n".join(lines)
    lines = [
        f"**{report['games']} games** in the last {report['days']} days — "
        f"{report['wins']}W/{report['losses']}L ({report['winrate_pct']}%), form: `{report['form']}`",
        f"Avg KDA: **{report['kda_line']}** ({report['avg_kda']}) · vision: {report['wards_per_min']} wards/min",
        f"Most played: {champs}",
    ]
    if report["cs10_delta_avg"] is not None:
        lines.append(
            f"CS@10 vs benchmark: **{report['cs10_delta_avg']:+.1f}** on average "
            f"(target: {report['cs10_bench']})"
        )
    if focus:
        lines.append(f"🎯 Focus of the week: **{focus}** — your most recurring lesson.")
    return "\n".join(lines)


def build_report_payload(report: dict, lang: str) -> dict:
    title = "Heti összefoglaló" if lang == "hu" else "Weekly summary"
    return {
        "username": "Sylqon Coach",
        "embeds": [
            {
                "title": f"📊 {title}",
                "description": render_text(report, lang),
                "color": 0x5865F2,
                "footer": {"text": f"Sylqon · {report['days']}d · {report['games']} games"},
            }
        ],
    }
