"""Open-build prompt compiler: draws situational items from the full Data
Dragon catalog rather than just the op.gg situational pool.

Only active when SYLQON_OPEN_BUILD=1. The existing pipeline is untouched.
"""
from __future__ import annotations

import json

from sylqon.data import static
from sylqon.data.catalog import Catalog
from sylqon.lcu.lobby import MatchContext


def _active_threat_tags(threat: dict) -> list[str]:
    """Map team_threat_summary() output to ITEM_COUNTER_TAGS keys."""
    tags: list[str] = []
    if threat.get("heavy_healing"):
        tags.append("anti_heal")
    if threat.get("tanks", 0) >= 1:
        tags.extend(["percent_pen", "tank_shred"])
    if threat.get("suppression") or threat.get("heavy_cc_count", 0) >= 3:
        tags.append("anti_cc")
    if threat.get("burst_ad") or threat.get("burst_ap"):
        tags.append("anti_burst")
    if threat.get("physical_threats", 0) >= 4:
        tags.append("armor")
    if threat.get("magic_threats", 0) >= 3:
        tags.append("mr")
    tags.append("percent_pen")  # always-on fallback
    return list(dict.fromkeys(tags))


def _merge_pools(
    catalog_items: list[dict],
    opgg_pool: list[dict],
    exclude_ids: set[int],
) -> list[dict]:
    """Merge op.gg pool + catalog items, deduped by ID, excluding fixed IDs.

    Op.gg items come first (★ meta picks).  Catalog additions are appended
    with an ``_is_opgg=False`` flag so the prompt can annotate each source.
    """
    seen: set[int] = set(exclude_ids)
    result: list[dict] = []

    for item in opgg_pool:
        iid = item.get("id")
        if iid is None or iid in seen:
            continue
        seen.add(iid)
        result.append({**item, "_is_opgg": True})

    for item in catalog_items:
        iid = item.get("id")
        if iid is None or iid in seen:
            continue
        seen.add(iid)
        result.append({**item, "_is_opgg": False})

    return result


def compile_open_prompt(ctx: MatchContext, candidate: dict, catalog: Catalog) -> str:
    """Build the counter-loadout prompt using the full DDragon catalog pool.

    Mirrors compile_prompt() from ai/prompts.py; differences:
    - Situational pool is the merged op.gg pool + threat-aware catalog items.
    - Each pool entry is labelled ★ op.gg meta pick or (catalog suggestion).
    - num_predict is set by the caller (runtime.py passes 768).
    """
    from sylqon import config as cfg
    from sylqon import loadout as loadout_mod
    from sylqon.ai.prompts import threat_directives, rune_directives, _tag_label

    threat = ctx.team_threat_summary()
    a1, a2 = loadout_mod.allowed_spells(candidate, ctx.my_role)
    def_spell1, def_spell2 = loadout_mod.deterministic_spells(candidate, ctx, a1)
    enemy_lines = (
        "\n".join(f"- {e.describe()}" for e in ctx.enemies)
        or "- unknown (enemy team hidden)"
    )
    ally_lines = (
        "\n".join(f"- {a.describe()}" for a in ctx.allies)
        or "- none locked yet"
    )
    doctrine_lines = "\n".join(f"- {d}" for d in threat_directives(threat))
    rune_lines = "\n".join(f"- {d}" for d in rune_directives(threat))

    boots = candidate.get("boots")
    core_items = candidate.get("core_items", [])
    all_items = candidate.get("items", [])
    situational_pool = candidate.get("situational_pool", [])
    situational_count = max(1, len(all_items) - 1 - len(core_items)) if core_items else 2

    boots_line = (boots or {}).get("name", "unknown")
    core_lines = "\n".join(f"{i+1}. {item['name']}" for i, item in enumerate(core_items))

    fixed_ids: set[int] = set()
    if boots:
        fixed_ids.add(boots["id"])
    for item in core_items:
        fixed_ids.add(item["id"])

    catalog_items = catalog.items_for_threat(
        _active_threat_tags(threat),
        exclude_ids=fixed_ids,
        limit=cfg.OPEN_BUILD_CATALOG_LIMIT,
    )
    merged_pool = _merge_pools(catalog_items, situational_pool, fixed_ids)

    pool_lines_list: list[str] = []
    for item in merged_pool:
        tag = _tag_label(item)
        src = "★ op.gg meta pick" if item.get("_is_opgg") else "(catalog suggestion)"
        desc = item.get("description") or item.get("plaintext", "") or "see in-game tooltip"
        pool_lines_list.append(f"- {item['name']}{tag}: {desc} — {src}")

    pool_lines = "\n".join(pool_lines_list) or "- (no situational options available)"

    item_section = (
        f"ITEM BUILD\n"
        f"Boots (fixed — do NOT include in output): {boots_line}\n\n"
        f"Core items (fixed, output these verbatim unless swapping 1 with any catalog item):\n"
        f"{core_lines}\n\n"
        f"Situational item pool — choose EXACTLY {situational_count} for the remaining slots "
        f"(★ op.gg meta picks are preferred; catalog suggestions can be used if clearly better "
        f"for the matchup):\n"
        f"{pool_lines}"
    )

    response_schema = {
        "core_items": [f"exactly {len(core_items)} names (default or swap 1 with any catalog item)"],
        "situational_items": [f"exactly {situational_count} names from the pool, ordered"],
        "keystone": "exact keystone name",
        "primary_runes": ["3 exact rune names from the keystone's tree"],
        "secondary_style": "one of Precision/Domination/Sorcery/Resolve/Inspiration",
        "secondary_runes": ["2 exact rune names from that tree"],
        "stat_shards": ["offense row pick", "flex row pick", "defense row pick"],
        "spell1": (
            f"KEEP \"{def_spell1}\" unless strongly justified; "
            f"if changing, ONLY one of {a1}"
        ),
        "spell2": (
            f"KEEP \"{def_spell2}\" unless strongly justified; "
            f"if changing, ONLY one of {a2}"
        ),
        "reasoning": "max 2 sentences",
    }

    return (
        f"You are a deterministic League of Legends loadout filter. Analyze the enemy threat "
        f"profile and select the optimal counter-loadout using ONLY the names provided below. "
        f"Do not invent names.\n\n"
        f"MY PICK: {ctx.my_champion}, role {ctx.my_role}\n\n"
        f"MY TEAM (already locked — note their summoners for combo potential):\n"
        f"{ally_lines}\n\n"
        f"ENEMY TEAM (their summoners change how you trade — e.g. enemy Cleanse/QSS beats your "
        f"CC, enemy Heal/Barrier shifts all-ins):\n"
        f"{enemy_lines}\n\n"
        f"TEAM THREAT SUMMARY: {json.dumps(threat)}\n\n"
        f"TACTICAL DOCTRINE (derived from the enemy comp — these directives override default "
        f"damage-greedy ordering; [tags] match the labels on pool items):\n"
        f"{doctrine_lines}\n\n"
        f"RUNE DOCTRINE (keep the base page; only adjust the flexible defensive picks as below):\n"
        f"{rune_lines}\n\n"
        f"{item_section}\n\n"
        f"RUNE POOL: keystones {list(static.KEYSTONES)}; minor runes by tree "
        f"{json.dumps({s: [n for n, t in static.RUNE_STYLE_OF_MINOR.items() if t == s] for s in static.RUNE_STYLES})}\n\n"
        f"STAT SHARD ROWS: offense {static.SHARD_ROW_OFFENSE}; flex {static.SHARD_ROW_FLEX}; "
        f"defense {static.SHARD_ROW_DEFENSE}\n\n"
        f"RULES:\n"
        f"- Apply the TACTICAL DOCTRINE first; fill any remaining slots with the highest-damage pool options.\n"
        f"- situational_items: pick EXACTLY {situational_count} from the pool; order by purchase priority.\n"
        f"- core_items: output unchanged unless 1 swap with a catalog item clearly counters a dominant threat.\n"
        f"- SUMMONER SPELLS: keep spell1=\"{def_spell1}\" and spell2=\"{def_spell2}\" by DEFAULT. "
        f"Only change a spell in a genuinely exceptional case, and even then pick ONLY from the "
        f"op.gg-observed options: spell1 ∈ {a1}, spell2 ∈ {a2}. "
        f"(For junglers spell1 is locked to Smite and ignored here.)\n"
        f"- Use only exact names that appear in the pools above.\n\n"
        f"Respond with raw JSON only, exactly this shape:\n"
        f"{json.dumps(response_schema)}"
    )
