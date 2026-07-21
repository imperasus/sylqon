"""Account-level macro coaching synthesis (feature A).

Turns the deterministic scorecard (``analysis/macro_coach.build_scorecard``) into
a short narrative + the **top 3 things to improve** via the shared Ollama engine.
Returns ``None`` when Ollama is unavailable so the API can serve the scorecard
alone (graceful degradation).
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

_TREND_WORD = {"up": "improving", "down": "declining", "flat": "flat"}


class MacroCoachAnalyzer:
    def __init__(self, engine) -> None:
        self.engine = engine

    def analyze(self, scorecard: dict, progress: dict | None = None) -> dict | None:
        if not self.engine.available():
            return None
        raw = self.engine.evaluate(self._build_prompt(scorecard, progress),
                                   options={"num_predict": 1024})
        if not isinstance(raw, dict):
            return None
        priorities = []
        for p in (raw.get("priorities") or [])[:3]:
            if isinstance(p, dict):
                priorities.append({
                    "title": str(p.get("title", "")).strip()[:80],
                    "detail": str(p.get("detail", "")).strip()[:240],
                })
        return {
            "narrative": str(raw.get("narrative", "")).strip()[:600],
            "priorities": priorities,
        }

    @staticmethod
    def _dim_lines(scorecard: dict) -> str:
        lines = []
        for d in scorecard.get("dimensions", []):
            trend = _TREND_WORD.get(d.get("trend", {}).get("dir"), "flat")
            lines.append(
                f"- {d['label']}: {d['value']} {d['unit']} "
                f"(score {d['score']}/100, trend: {trend})")
        return "\n".join(lines) or "- no data"

    @staticmethod
    def _progress_line(progress: dict | None) -> str:
        """One line on movement vs the previous window, when we have one."""
        if not progress or not progress.get("available"):
            return ""
        delta = progress.get("overall_delta") or 0
        sign = "+" if delta > 0 else ""
        return (f"\n**Movement vs the previous {progress.get('compared_games', 0)} games:**\n"
                f"- Overall score {progress.get('previous_overall')} -> "
                f"{progress.get('previous_overall', 0) + delta} ({sign}{delta} points)\n")

    def _build_prompt(self, sc: dict, progress: dict | None = None) -> str:
        wr = sc.get("win_rate")
        wr_pct = f"{round(wr * 100)}%" if wr is not None else "—"
        results = " ".join(sc.get("recent_results", [])) or "—"
        return f"""You are a League of Legends macro coach reviewing a player's
recent form across multiple games (not a single match).

IMPORTANT LEAGUE OF LEGENDS DOMAIN FACTS (DO NOT CONTRADICT THESE):
- **CS** always means **Creep Score**: minions and jungle monsters last-hit. It
  measures farming / gold income efficiency, NEVER combat points or a "battle
  score".
- High CS/min → good farming and item timings; low CS/min → gold left on the map.
- Vision score measures warding / map control; deaths measure positioning and
  risk management.
- Each dimension score is already normalised 0-100 against that player's role
  benchmark — treat 50 as average, 70+ as strong, below 40 as a clear weakness.

**Form over the last {sc.get('games_analyzed', 0)} games:**
- Win rate: {wr_pct}
- Recent results (newest first): {results}
- Overall score: {sc.get('overall', 0)}/100 (trend: {_TREND_WORD.get(sc.get('overall_trend', {}).get('dir'), 'flat')})
{self._progress_line(progress)}
**Dimensions:**
{self._dim_lines(sc)}

TASK:
Write a concise, constructive **macro coaching summary in ENGLISH**.

Requirements:
- narrative: 1–2 sentences on the overall form (use concrete numbers). If a
  movement section is present, say whether they are trending up or down.
- priorities: EXACTLY the 3 most impactful things to improve, prioritising the
  lowest-scoring and downward-trending dimensions. Each priority is an object
  with a short "title" (max ~6 words) and a "detail" (1–2 concrete, actionable
  sentences with numbers/targets for the next games).
- Be specific and data-backed; avoid generic advice.
- Write in English only.

Respond ONLY with valid JSON in this format:
{{"narrative": "...", "priorities": [{{"title": "...", "detail": "..."}}, {{"title": "...", "detail": "..."}}, {{"title": "...", "detail": "..."}}]}}"""
