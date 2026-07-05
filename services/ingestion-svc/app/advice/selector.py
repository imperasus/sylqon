"""Pick the single most important lesson — 'one advice per match' is the product."""
from __future__ import annotations

from app.advice.heuristics import Finding

# Tie-break order when severities match: positioning kills > farming > vision >
# itemization > objectives (macro comes last for the Iron–Gold audience — the
# fundamentals compound harder).
_PRIORITY = ["death_context", "cs_benchmark", "vision", "item_timing", "objective_presence"]


def select_top(findings: list[Finding]) -> Finding | None:
    if not findings:
        return None
    return sorted(
        findings,
        key=lambda f: (-f.severity, _PRIORITY.index(f.type) if f.type in _PRIORITY else 99),
    )[0]
