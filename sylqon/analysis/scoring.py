"""0-100 champion scoring for universal, role-based recommendations.

Adapted from the v2 implementation examples but wired to the *real* store:
  - meta tier comes from ``Champion.op_gg_stats[role]['tier']`` (op.gg uses
    **0 = OP** .. 5 = weak);
  - win rate comes from the build row, falling back to the per-role meta win rate
    (both stored as percentages by the ingest layer);
  - counter advantages are signed ``[-10, +10]`` and synergies ``[0, 10]``.

Weighted blend (player-aware): counter .30 / synergy .20 / meta .20 /
win-rate .10 / comfort .20. The comfort term encodes how well the *player* can
play the champion (pool membership + personal win rate from match history), so
the recommendation favours playable picks while a dominant counter can still
override an off-pool option.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from sylqon.db import queries
from sylqon.db.schema import Champion

# op.gg tier (0 = OP) -> 0..100. Both 0 and 1 are top-tier in the lane-meta feed.
TIER_SCORE = {0: 100, 1: 95, 2: 80, 3: 65, 4: 50, 5: 35}

# Comfort baselines (0..100): an off-pool champion the player has no recent
# games on starts low; a pool champion without a recent sample sits mid-high.
COMFORT_OFF_POOL = 42.0
COMFORT_IN_POOL = 68.0
COMFORT_MIN_GAMES = 5  # personal win rate only trusted past this sample size


class ChampionScorer:
    """Score every champion that can play a role against the current draft."""

    def __init__(self) -> None:
        self.weights = {
            "counter": 0.30,
            "synergy": 0.20,
            "meta": 0.20,
            "win_rate": 0.10,
            "comfort": 0.20,
        }

    # -- public ---------------------------------------------------------------
    def get_top_recommendations(self, session: Session, role: str,
                                ally_ids: list[int], enemy_ids: list[int],
                                pool_names: set[str] | None = None,
                                personal_stats: dict[str, dict] | None = None,
                                limit: int = 5) -> list[dict]:
        scored = []
        for champ in queries.champions_for_role(session, role):
            scores = self.score_champion(session, champ, role, ally_ids, enemy_ids,
                                         pool_names=pool_names, personal_stats=personal_stats)
            in_pool = bool(pool_names) and champ.name in pool_names
            scored.append({
                "champion": {"id": champ.id, "name": champ.name,
                             "slug": champ.slug, "riot_key": champ.riot_key},
                "score": scores,
                "in_pool": in_pool,
                "reasoning": self._reasoning(scores, in_pool),
            })
        scored.sort(key=lambda x: x["score"]["total"], reverse=True)
        return scored[:limit]

    def score_champion(self, session: Session, champ: Champion, role: str,
                       ally_ids: list[int], enemy_ids: list[int],
                       pool_names: set[str] | None = None,
                       personal_stats: dict[str, dict] | None = None) -> dict:
        counter = self._counter_score(session, champ.id, role, enemy_ids)
        synergy = self._synergy_score(session, champ.id, role, ally_ids)
        meta = self._meta_score(champ, role)
        win_rate = self._win_rate_score(session, champ.id, role)
        comfort = self._comfort_score(champ.name, pool_names, personal_stats)
        total = (counter * self.weights["counter"]
                 + synergy * self.weights["synergy"]
                 + meta * self.weights["meta"]
                 + win_rate * self.weights["win_rate"]
                 + comfort * self.weights["comfort"])
        return {
            "total": round(total, 1),
            "counter": round(counter, 1),
            "synergy": round(synergy, 1),
            "meta": round(meta, 1),
            "win_rate": round(win_rate, 1),
            "comfort": round(comfort, 1),
        }

    # -- components -----------------------------------------------------------
    def _counter_score(self, session: Session, champion_id: int, role: str,
                       enemy_ids: list[int]) -> float:
        """Average matchup advantage vs the enemies, mapped -10..+10 -> 0..100.
        Missing matchups count as neutral (0). No enemies -> neutral 50."""
        if not enemy_ids:
            return 50.0
        advantages = queries.counter_map(session, champion_id, role, enemy_ids)
        avg = sum(advantages.get(eid, 0.0) for eid in enemy_ids) / len(enemy_ids)
        return max(0.0, min(100.0, ((avg + 10) / 20) * 100))

    def _synergy_score(self, session: Session, champion_id: int, role: str,
                       ally_ids: list[int]) -> float:
        """Average synergy with allies (0..10) -> 0..100. Missing pairs count as
        neutral (5). No allies -> neutral 50."""
        if not ally_ids:
            return 50.0
        synergies = queries.synergy_map(session, champion_id, role, ally_ids)
        avg = sum(synergies.get(aid, 5.0) for aid in ally_ids) / len(ally_ids)
        return max(0.0, min(100.0, (avg / 10) * 100))

    def _meta_score(self, champ: Champion, role: str) -> float:
        stats = (champ.op_gg_stats or {}).get(role) or {}
        tier = stats.get("tier")
        if tier is None:
            return 50.0
        return float(TIER_SCORE.get(int(tier), 50))

    def _win_rate_score(self, session: Session, champion_id: int, role: str) -> float:
        """Win rate (percentage) -> 0..100. 40%->20, 45%->40, 50%->70, 55%+->100.
        Below 45% keeps a gentle slope (not a flat floor) so a merely-weak pick is
        still ranked above a genuinely-bad one when other terms are close."""
        wr = None
        build = queries.build_for(session, champion_id, role)
        if build is not None and build.win_rate is not None:
            wr = build.win_rate
        else:
            champ = session.get(Champion, champion_id)
            wr = ((champ.op_gg_stats or {}).get(role) or {}).get("win_rate") if champ else None
        if wr is None:
            return 50.0
        if wr < 45:
            score = 40 - (45 - wr) * 2          # 45%->40, 40%->30, 35%->20 (floored)
        elif wr < 50:
            score = 40 + (wr - 45) * (30 / 5)
        elif wr < 55:
            score = 70 + (wr - 50) * (30 / 5)
        else:
            score = 100.0
        return max(0.0, min(100.0, score))

    def _comfort_score(self, name: str, pool_names: set[str] | None,
                       personal_stats: dict[str, dict] | None) -> float:
        """How well the *player* can pilot this champion. Personal win rate (over
        a meaningful sample) dominates; otherwise pool membership is the signal,
        and an unfamiliar off-pool champion gets a low baseline so a strong draft
        edge has to justify recommending it."""
        in_pool = bool(pool_names) and name in pool_names
        personal = (personal_stats or {}).get(name)
        if personal and personal.get("games", 0) >= COMFORT_MIN_GAMES:
            wr = personal.get("win_rate", 0.0) * 100
            if wr < 45:
                base = 35.0
            elif wr < 50:
                base = 50 + (wr - 45) * 4          # 45%->50, 50%->70
            elif wr < 55:
                base = 70 + (wr - 50) * 4          # 50%->70, 55%->90
            else:
                base = 95.0
            if in_pool:
                base += 5
            return max(20.0, min(100.0, base))
        if in_pool:
            return COMFORT_IN_POOL
        return COMFORT_OFF_POOL

    # -- reasoning ------------------------------------------------------------
    @staticmethod
    def _reasoning(scores: dict, in_pool: bool = False) -> str:
        reasons = []
        if scores["counter"] >= 75:
            reasons.append("Strong counter to enemy composition")
        elif scores["counter"] <= 30:
            reasons.append("Countered by enemy picks")
        if scores["meta"] >= 85:
            reasons.append("Top tier in current meta")
        if scores["synergy"] >= 75:
            reasons.append("Excellent synergy with team")
        if scores["win_rate"] >= 80:
            reasons.append("High win rate")
        if scores.get("comfort", 50) >= 80:
            reasons.append("You play this well")
        elif not in_pool:
            reasons.append("Off-pool — a power pick, not a comfort one")
        if not reasons:
            reasons.append("Balanced option for this matchup")
        return "; ".join(reasons)
