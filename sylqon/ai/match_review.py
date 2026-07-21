"""Post-game match analysis (v2).

Generates a short, constructive review (summary + strengths + weaknesses + tips)
from a stored match's stats via the shared Ollama engine.
Returns ``None`` when Ollama is unavailable so the API can degrade gracefully.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class MatchReviewAnalyzer:
    def __init__(self, engine) -> None:
        self.engine = engine

    def analyze_match(self, match_data: dict) -> dict | None:
        if not self.engine.available():
            return None
        # Summary + 3x3 bullet lists can exceed the default 512-token budget;
        # give it headroom so the JSON isn't truncated.
        raw = self.engine.evaluate(self._build_prompt(match_data),
                                   options={"num_predict": 1024})
        if not isinstance(raw, dict):
            return None
        clip = lambda xs: [str(x) for x in (xs or [])][:3]
        return {
            "summary": str(raw.get("summary", "")).strip()[:600] or "Analysis unavailable.",
            "strengths": clip(raw.get("strengths")),
            "weaknesses": clip(raw.get("weaknesses")),
            "tips": clip(raw.get("tips")),
        }

    @staticmethod
    def _format_timeline(timeline: list[dict]) -> str:
        if not timeline:
            return "No timeline data"
        lines = []
        for e in timeline[:5]:
            t = (e.get("time", 0) or 0) / 60
            lines.append(f"- {t:.1f} min: {e.get('event', '')}")
        return "\n".join(lines)

    def _build_prompt(self, md: dict) -> str:
        kda = md.get("kda", {})
        stats = md.get("stats", {})
        deaths = max(kda.get("deaths", 0), 1)
        kda_ratio = (kda.get("kills", 0) + kda.get("assists", 0)) / deaths
        dur_min = (md.get("duration", 0) or 0) / 60

        return f"""You are a League of Legends coach analyzing a player's performance.

IMPORTANT LEAGUE OF LEGENDS DOMAIN FACTS (DO NOT CONTRADICT THESE):
- In League of Legends, **CS** always means **Creep Score**: the number of minions and jungle monsters a player has last-hit.
- CS and CS per minute measure **farming / gold income efficiency**, NOT combat points, damage dealt, or any kind of “battle score”.
- High CS / CS per minute → good farming, strong economy, good item timings.
- Low CS / CS per minute → weak farming, missed gold, delayed item spikes.

Example of good phrasing:
- \"210 CS in 28 minutes (~7.5 CS/min) is strong farming — steady gold income and on-time item spikes.\"
- \"150 CS in 30 minutes (~5 CS/min) is low: a lot of minions, and so a lot of gold, left on the map.\"

Now you will receive the match stats. Use them as hard facts.

**Match data:**
- Champion: {md.get('champion')} ({md.get('role')})
- Result: {md.get('result')}
- Duration: {dur_min:.1f} minutes
- KDA: {kda.get('kills', 0)}/{kda.get('deaths', 0)}/{kda.get('assists', 0)} (ratio: {kda_ratio:.2f})
- Gold: {stats.get('gold', 0):,}
- Damage to champions: {stats.get('total_damage', 0):,}
- Damage taken: {stats.get('damage_taken', 0):,}
- Vision score: {stats.get('vision_score', 0)}
- CS: {stats.get('cs', 0)} ({stats.get('cs_per_min', 0)} CS/min)

**Timeline:**
{self._format_timeline(md.get('timeline', []))}

TASK:
Write a concise, constructive **post-game analysis in ENGLISH**.

Requirements:
- Summary: 1–2 sentences overall assessment.
- Strengths: 2–3 specific, data-backed points.
- Weaknesses: 2–3 specific areas to improve.
- Tips: 2–3 concrete, actionable suggestions for the next game.
- Even in a win, find things to improve; even in a loss, find positives.
- Use concrete numbers from the stats where relevant.

Respond ONLY with valid JSON in this format:
{{"summary": "...", "strengths": ["..."], "weaknesses": ["..."], "tips": ["..."]}}"""
