"""Post-lock matchup analytics for the final pick.

Once the player's champion is locked, this turns the same scoring + pairwise
data the live draft already used into a finished-pick scorecard:

  - the champion's own 0-100 component scores (counter / synergy / meta /
    win-rate / comfort) for the locked role;
  - the per-ally synergy and per-enemy counter values, on op.gg's signed scale,
    so the dashboard can show a number under each portrait;
  - the direct lane matchup (the same-role enemy, with their threat profile and
    the head-to-head advantage).

Pure and DB-only (no Ollama) so it publishes instantly alongside the build. The
optional AI early/mid/late game plan is generated separately (``ai.lane_plan``)
and merged in off-thread, so this never blocks the injection path. Best-effort:
the caller wraps it in try/except and the post-lock view degrades to whatever
fields are present.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from sylqon.analysis.scoring import ChampionScorer
from sylqon.data.catalog import Catalog
from sylqon.db import queries
from sylqon.db.schema import Champion
from sylqon.lcu.lobby import MatchContext


def _win_pct(session: Session, champ: Champion, role: str) -> float | None:
    """Raw op.gg win rate (percentage) for display, mirroring the scorer's
    source order: the build row first, then the per-role meta stat."""
    build = queries.build_for(session, champ.id, role)
    if build is not None and build.win_rate is not None:
        return round(build.win_rate, 1)
    wr = ((champ.op_gg_stats or {}).get(role) or {}).get("win_rate")
    return round(wr, 1) if wr is not None else None


def _lane_score(counter_score: float, lane_advantage: float | None) -> float:
    """A laning-phase read (0-100). The ``counter`` component already averages
    the whole enemy team; when we know the *direct* lane opponent's advantage we
    weight that head-to-head heavier, since it dominates the laning phase."""
    if lane_advantage is None:
        return round(counter_score, 1)
    lane = max(0.0, min(100.0, ((lane_advantage + 10) / 20) * 100))
    return round(counter_score * 0.4 + lane * 0.6, 1)


def _avg(values: list) -> float | None:
    present = [v for v in values if v is not None]
    return round(sum(present) / len(present), 1) if present else None


def compute_matchup(session: Session, ctx: MatchContext, catalog: Catalog, *,
                    pool_names: set[str] | None = None,
                    personal_stats: dict[str, dict] | None = None) -> dict | None:
    """Build the post-lock scorecard for ``ctx.my_champion``. Returns ``None``
    when the locked champion isn't in the DB (e.g. catalog ahead of an unsynced
    DB) so the caller can simply omit the panel."""
    my_name = ctx.my_champion
    if not my_name:
        return None
    me = session.query(Champion).filter_by(name=my_name).first()
    if me is None and ctx.my_champion_id:
        me = session.query(Champion).filter_by(riot_key=ctx.my_champion_id).first()
    if me is None:
        return None
    role = ctx.my_role

    allies = [a for a in ctx.allies if a.locked]
    enemies = [e for e in ctx.enemies if e.locked]
    ally_ids = queries.champion_ids_by_name(session, [a.name for a in allies])
    enemy_ids = queries.champion_ids_by_name(session, [e.name for e in enemies])

    scores = ChampionScorer().score_champion(
        session, me, role,
        list(ally_ids.values()), list(enemy_ids.values()),
        pool_names=pool_names, personal_stats=personal_stats)

    syn_map = queries.synergy_map(session, me.id, role, list(ally_ids.values()))
    cnt_map = queries.counter_map(session, me.id, role, list(enemy_ids.values()))

    def slug_of(pick) -> str:
        return (catalog.champion_by_key(pick.champion_id) or {}).get("id", "")

    synergies = []
    for a in allies:
        val = syn_map.get(ally_ids.get(a.name))
        synergies.append({"name": a.name, "slug": slug_of(a), "role": a.role,
                          "value": round(val, 1) if val is not None else None})

    counters = []
    for e in enemies:
        val = cnt_map.get(enemy_ids.get(e.name))
        is_lane = bool(role and e.role == role)
        counters.append({"name": e.name, "slug": slug_of(e), "role": e.role,
                         "value": round(val, 1) if val is not None else None,
                         "is_lane_opponent": is_lane})

    opp = next((e for e in enemies if role and e.role == role), None)
    lane_adv = cnt_map.get(enemy_ids.get(opp.name)) if opp is not None else None
    lane_opponent = None
    if opp is not None:
        lane_opponent = {
            "name": opp.name, "slug": slug_of(opp), "role": opp.role,
            "damage_type": opp.damage_type,
            "threats": list(opp.threats), "tags": list(opp.tags),
            "advantage": round(lane_adv, 1) if lane_adv is not None else None,
        }

    return {
        "champion": {
            "name": me.name, "slug": me.slug, "role": role,
            "tier": ((me.op_gg_stats or {}).get(role) or {}).get("tier"),
        },
        "scores": scores,
        "win_rate_pct": _win_pct(session, me, role),
        "lane_score": _lane_score(scores["counter"], lane_adv),
        "synergies": synergies,
        "synergy_avg": _avg([s["value"] for s in synergies]),
        "counters": counters,
        "counter_avg": _avg([c["value"] for c in counters]),
        "lane_opponent": lane_opponent,
    }
