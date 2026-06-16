"""Champion recommendation: which of the player's pool champions to pick,
given the allies already locked (synergy) and the enemies revealed (counter).

The pool is every champion we can build a loadout for in the player's role
(MetaCache.champions_for_role). A deterministic heuristic scores each candidate
from class tags + threat profiles, so a recommendation exists even with Ollama
offline; Ollama then makes the final qualitative call, constrained to the pool.
No network/MCP on this path — synergy/counter are derived locally, consistent
with the live-match design.
"""
from __future__ import annotations

import json
import logging

from sylqon.data import static
from sylqon.data.catalog import Catalog
from sylqon.lcu.lobby import MatchContext, _damage_type, _threats

log = logging.getLogger(__name__)


def _tags(pick) -> set:
    return set(pick["tags"] if isinstance(pick, dict) else pick.tags)


def _pick_threats(pick) -> set:
    return set(pick["threats"] if isinstance(pick, dict) else pick.threats)


def _is_engage(pick) -> bool:
    return "heavy_cc" in _pick_threats(pick) and bool({"Tank", "Fighter"} & _tags(pick))


def _is_frontline(pick) -> bool:
    return bool({"Tank", "Fighter"} & _tags(pick))


def _is_enchanter(pick) -> bool:
    return "Support" in _tags(pick) and "heavy_healing" in _pick_threats(pick)


def build_candidates(ctx: MatchContext, pool: list[str], catalog: Catalog) -> list[dict]:
    """Resolve the role pool into scoreable candidate profiles, dropping any
    champion already taken by either team."""
    taken = {p.name for p in ctx.enemies} | {p.name for p in ctx.allies}
    out = []
    for name in pool:
        if name in taken:
            continue
        info = catalog.champion_by_name(name) or {}
        out.append({
            "name": name,
            "tags": info.get("tags", []),
            "damage_type": _damage_type(info),
            "threats": _threats(name),
        })
    return out


def score_candidate(cand: dict, ctx: MatchContext) -> tuple[int, list[str]]:
    """Heuristic synergy/counter score for one candidate. Positive = good pick
    into this draft. Returns (score, human-readable notes)."""
    threat = ctx.team_threat_summary()
    tags = set(cand["tags"])
    notes: list[str] = []
    score = 0

    # --- counter signals (vs the enemy comp) --------------------------------
    if threat["tanks"] >= 2 and "Marksman" in tags:
        score += 2
        notes.append("+2 sustained DPS shreds the enemy's 2+ tanks")
    if (threat["burst_ad"] or threat["burst_ap"]) and _is_frontline(cand):
        score += 2
        notes.append("+2 durable frontline survives enemy burst/assassins")
    if (threat["burst_ad"] or threat["burst_ap"]) and tags & {"Marksman", "Mage"} \
            and not _is_frontline(cand):
        score -= 1
        notes.append("-1 squishy into enemy burst threats")
    if threat["heavy_cc_count"] >= 3 and "Marksman" in tags:
        score -= 1
        notes.append("-1 immobile carry into heavy enemy CC")
    if any("poke" in e.threats for e in ctx.enemies) and _is_engage(cand):
        score += 2
        notes.append("+2 hard engage punishes the enemy poke comp")

    # --- synergy signals (vs allies already locked) -------------------------
    ally_has_engage = any(_is_engage(a) for a in ctx.allies)
    ally_has_enchanter = any(_is_enchanter(a) for a in ctx.allies)
    ally_has_frontline = any(_is_frontline(a) for a in ctx.allies)
    ally_dmg = {a.damage_type for a in ctx.allies}

    if (ally_has_engage or ally_has_enchanter) and tags & {"Marksman", "Mage"}:
        score += 2
        notes.append("+2 scaling carry to cash in ally engage/peel")
    if not ally_has_frontline and _is_frontline(cand):
        score += 1
        notes.append("+1 team lacks a frontline; this adds one")
    if ctx.allies and ally_dmg == {"AD"} and cand["damage_type"] == "AP":
        score += 1
        notes.append("+1 diversifies an all-AD team's damage")
    if ctx.allies and ally_dmg == {"AP"} and cand["damage_type"] == "AD":
        score += 1
        notes.append("+1 diversifies an all-AP team's damage")

    return score, notes


def heuristic_rank(ctx: MatchContext, candidates: list[dict]) -> list[dict]:
    """Rank candidates by heuristic score (stable on ties → pool order)."""
    ranked = []
    for cand in candidates:
        score, notes = score_candidate(cand, ctx)
        ranked.append({**cand, "score": score, "notes": notes})
    ranked.sort(key=lambda c: c["score"], reverse=True)
    return ranked


def compile_pick_prompt(ctx: MatchContext, ranked: list[dict]) -> str:
    """Prompt Ollama to pick from the (pre-scored) pool, weighing the enemy and
    ally summoner spells and the heuristic notes."""
    pool_lines = "\n".join(
        f"- {c['name']} ({'/'.join(c['tags']) or 'unknown'}, {c['damage_type']}; "
        f"heuristic {c['score']:+d}: {'; '.join(c['notes']) or 'no strong signal'})"
        for c in ranked
    ) or "- (no available pool champions)"
    enemy_lines = "\n".join(f"- {e.describe()}" for e in ctx.enemies) or "- none revealed yet"
    ally_lines = "\n".join(f"- {a.describe()}" for a in ctx.allies) or "- none locked yet"
    names = [c["name"] for c in ranked]
    schema = {
        "pick": "one champion name from the pool",
        "alternatives": ["up to 2 other pool names, best first"],
        "reasoning": "max 2 sentences citing synergy and counter",
    }
    return f"""You are a League of Legends draft analyst. Recommend exactly ONE champion for the player to pick for role {ctx.my_role}, choosing ONLY from the candidate pool. Weigh synergy with allies and counter vs enemies, including their summoner spells (e.g. enemy Cleanse/QSS beats your hard CC; enemy Heal/Ignite shifts trades).

ALLIES ALREADY LOCKED (build synergy with these):
{ally_lines}

ENEMIES REVEALED (counter these):
{enemy_lines}

CANDIDATE POOL (pick from these names only; heuristic score pre-computed):
{pool_lines}

RULES:
- "pick" MUST be one of: {names}
- Prefer high heuristic scores but override when the spells/comp clearly justify it.
- Favor champions that synergise with ally engage/peel and exploit enemy weaknesses.

Respond with raw JSON only, exactly this shape:
{json.dumps(schema)}"""


def compile_universe_pick_prompt(ctx: MatchContext, candidates: list[dict]) -> str:
    """Prompt Ollama to pick the single best champion for the role from the
    *whole available pool* (every pickable champion for the lane, not just the
    player's own pool), using the pre-computed 0-100 component scores. Each
    candidate is flagged in-pool / off-pool so the model can weigh the player's
    comfort against a raw draft advantage."""
    cand_lines = []
    for c in candidates:
        ch = c["champion"]
        s = c["score"]
        tag = "in your pool" if c.get("in_pool") else "off-pool"
        cand_lines.append(
            f"- {ch['name']} (overall {s['total']:.0f}; counter {s['counter']:.0f}, "
            f"synergy {s['synergy']:.0f}, meta {s['meta']:.0f}, comfort {s['comfort']:.0f}; {tag})"
        )
    cand_block = "\n".join(cand_lines) or "- (no scored candidates)"
    enemy_lines = "\n".join(f"- {e.describe()}" for e in ctx.enemies) or "- none revealed yet"
    ally_lines = "\n".join(f"- {a.describe()}" for a in ctx.allies) or "- none locked yet"
    names = [c["champion"]["name"] for c in candidates]
    schema = {
        "pick": "one champion name — the best overall pick from the list",
        "alternatives": ["up to 2 other names, best first"],
        "reasoning": "max 2 sentences: cite counter/synergy and call out if it is an off-pool power pick",
    }
    return f"""You are a League of Legends draft analyst. Recommend exactly ONE champion for role {ctx.my_role}, choosing ONLY from the scored candidate list below. These are ALL pickable champions for the lane, ranked by a blend of counter, synergy, meta and the player's comfort. Pick the strongest pick into THIS draft — you may favour an off-pool champion when its counter/synergy edge clearly outweighs the comfort gap, but prefer a comfort pick when the draft value is close. Weigh enemy summoner spells (e.g. Cleanse/QSS beats hard CC).

ALLIES ALREADY LOCKED (synergy):
{ally_lines}

ENEMIES REVEALED (counter these):
{enemy_lines}

SCORED CANDIDATES (pick from these names only):
{cand_block}

RULES:
- "pick" MUST be one of: {names}
- Prefer higher overall scores but override when spells/comp clearly justify it.

Respond with raw JSON only, exactly this shape:
{json.dumps(schema)}"""


def apply_universe_ai_pick(candidates: list[dict], ai: dict | None) -> dict | None:
    """Resolve the AI's universe pick to a candidate entry, validated against the
    scored list. Returns the chosen candidate dict augmented with AI reasoning +
    source, or None when there are no candidates. Falls back to the top-scored
    candidate when the AI output is unusable."""
    if not candidates:
        return None
    by_name = {c["champion"]["name"]: c for c in candidates}
    chosen = candidates[0]
    source = "heuristic"
    reasoning = chosen.get("reasoning", "")
    alternatives = [c["champion"]["name"] for c in candidates[1:3]]

    if isinstance(ai, dict):
        ai_pick = ai.get("pick")
        if isinstance(ai_pick, str) and ai_pick in by_name:
            chosen = by_name[ai_pick]
            source = "ollama"
            reasoning = str(ai.get("reasoning", ""))[:300] or chosen.get("reasoning", "")
            ai_alts = ai.get("alternatives", [])
            if isinstance(ai_alts, list):
                valid = [a for a in ai_alts if isinstance(a, str)
                         and a in by_name and a != ai_pick]
                if valid:
                    alternatives = valid[:2]

    return {**chosen, "source": source, "reasoning": reasoning, "alternatives": alternatives}


def apply_ai_pick(ranked: list[dict], ai: dict | None) -> dict:
    """Merge the AI's choice onto the heuristic ranking, validated against the
    pool. Falls back to the heuristic top pick when the AI output is unusable."""
    pool_names = [c["name"] for c in ranked]
    by_name = {c["name"]: c for c in ranked}
    heuristic_top = pool_names[0] if pool_names else None

    pick = heuristic_top
    source = "heuristic"
    reasoning = ""
    alternatives: list[str] = [n for n in pool_names[1:3]]

    if isinstance(ai, dict):
        ai_pick = ai.get("pick")
        if isinstance(ai_pick, str) and ai_pick in by_name:
            pick = ai_pick
            source = "ollama"
            reasoning = str(ai.get("reasoning", ""))[:300]
            ai_alts = ai.get("alternatives", [])
            if isinstance(ai_alts, list):
                valid = [a for a in ai_alts if isinstance(a, str)
                         and a in by_name and a != pick]
                if valid:
                    alternatives = valid[:2]
        else:
            log.debug("AI pick %r not in pool; keeping heuristic %r", ai_pick, heuristic_top)

    if pick is None:
        return {"pick": None, "alternatives": [], "reasoning": "", "source": "none",
                "scored": []}
    return {
        "pick": pick,
        "alternatives": alternatives,
        "reasoning": reasoning or "; ".join(by_name[pick]["notes"]),
        "source": source,
        "scored": [{"name": c["name"], "score": c["score"], "notes": c["notes"]}
                   for c in ranked],
    }
