"""Prompt compiler for per-champion mission generation (overlay coach v2).

Runs at the END of a game — never on the latency-sensitive live path — so a slow
or unavailable Ollama simply leaves the champion's queue untouched (the static
role catalog covers the next game). The model only *selects + tunes + flavours*
missions from the closed vocabulary in ``livegame.missions``; it never invents a
mechanic the live evaluators cannot score. Every emitted mission is re-validated
with ``normalize_mission`` before it is trusted, mirroring the project-wide rule
that AI output is checked against static tables.
"""
from __future__ import annotations

import json

from sylqon.livegame.missions import (
    CS_PER_MIN,
    FARM_CS_DELTA,
    GANK_ASSIST,
    MISSION_TYPE_SCHEMA,
    NO_DEATH,
    OBJECTIVE,
    ROAM_ASSIST,
    WARDING,
)

# Short human description per type, shown to the model alongside the param schema.
_TYPE_DESC = {
    NO_DEATH: "survive a duration without dying",
    FARM_CS_DELTA: "gain a CS amount (optionally without dying)",
    CS_PER_MIN: "sustain a CS/min rate over a window",
    OBJECTIVE: "secure dragons/heralds/barons/towers",
    WARDING: "place/clear a number of wards (vision score)",
    ROAM_ASSIST: "roam for kills/assists away from lane",
    GANK_ASSIST: "convert ganks into kills/assists",
}


def _schema_doc() -> str:
    """Render MISSION_TYPE_SCHEMA into a compact, model-readable param spec so the
    prompt and the validator can never drift apart."""
    lines = []
    for mtype, schema in MISSION_TYPE_SCHEMA.items():
        parts = []
        for field_, (lo, hi) in {**schema.get("int", {}), **schema.get("float", {})}.items():
            parts.append(f"{field_} ({lo}-{hi}, required)")
        for field_, (lo, hi) in schema.get("opt_int", {}).items():
            parts.append(f"{field_} ({lo}-{hi}, optional)")
        for field_ in schema.get("opt_bool", ()):
            parts.append(f"{field_} (true/false, optional)")
        for field_, allowed in schema.get("enum_list", {}).items():
            parts.append(f"{field_} (subset of {list(allowed)}, required)")
        lines.append(f'- "{mtype}": {_TYPE_DESC.get(mtype, "")}; params: {", ".join(parts)}')
    return "\n".join(lines)


def _weakness_hints(last_game: dict) -> list[str]:
    """Turn the just-played game's stats into plain coaching directives the model
    should bias the generated missions toward."""
    kda = last_game.get("kda") or {}
    stats = last_game.get("stats") or {}
    hints: list[str] = []
    deaths = kda.get("deaths", 0)
    if deaths >= 6:
        hints.append(f"Died {deaths} times — prioritise a '{NO_DEATH}' mission with a "
                     "higher reward, and add no_death:true to any farm goal.")
    elif deaths >= 4:
        hints.append(f"Died {deaths} times — include at least one survival-focused mission.")
    cspm = stats.get("cs_per_min", 0) or 0
    if cspm and cspm < 6.5:
        hints.append(f"Low farm ({cspm} CS/min) — include a farm or CS/min mission.")
    vision = stats.get("vision_score", 0) or 0
    if vision and vision < 15:
        hints.append(f"Low vision ({vision}) — include a warding mission.")
    if last_game.get("result") == "Loss":
        hints.append("Lost the game — keep goals achievable to rebuild confidence.")
    if not hints:
        hints.append("Solid game — set slightly tougher goals to keep improving.")
    return hints


def compile_mission_prompt(champion: str, role: str, last_game: dict,
                           needed: int, existing_texts: list[str] | None = None) -> str:
    """Build the generation prompt for ``needed`` fresh missions on ``champion``
    (role ``role``), biased to the weaknesses shown in ``last_game`` and avoiding
    the still-pending ``existing_texts``."""
    kda = last_game.get("kda") or {}
    stats = last_game.get("stats") or {}
    summary = {
        "result": last_game.get("result", "?"),
        "kda": f"{kda.get('kills', 0)}/{kda.get('deaths', 0)}/{kda.get('assists', 0)}",
        "cs_per_min": stats.get("cs_per_min", 0),
        "vision_score": stats.get("vision_score", 0),
    }
    hint_lines = "\n".join(f"- {h}" for h in _weakness_hints(last_game))
    avoid = "; ".join(t for t in (existing_texts or []) if t) or "(none)"
    response_schema = {
        "missions": [{
            "type": "<one type key from the list>",
            "params": {"<param>": "<value within range>"},
            "reward_points": f"int {10}-{50} (harder = higher)",
            "text": "one short imperative sentence, <=80 chars, naming the champion's improvement",
        }]
    }

    return f"""You are a League of Legends improvement coach. Generate EXACTLY {needed} \
personalised practice mission(s) for the player's next game on {champion} ({role}).

LAST GAME ON {champion}: {json.dumps(summary)}

COACHING FOCUS (bias the missions toward these):
{hint_lines}

ALLOWED MISSION TYPES (use ONLY these; pick params strictly within range):
{_schema_doc()}

AVOID repeating these still-active missions: {avoid}

RULES:
- Output EXACTLY {needed} mission object(s).
- Use ONLY the type keys and params listed above; never invent a type or param.
- Every numeric param MUST sit inside its stated range.
- Make the text specific to {champion} and the coaching focus, imperative, <=80 chars.

Respond with raw JSON only, exactly this shape:
{json.dumps(response_schema)}"""
