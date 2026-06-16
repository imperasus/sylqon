"""Prompt compiler: match context + cached candidate pool -> Ollama prompt.

The model acts purely as a data filter / tactical analyst: it may only pick
from the candidate pools handed to it, and must answer in raw JSON. The
TACTICAL DOCTRINE section turns the enemy threat summary into explicit
selection/ordering rules (pro-analyst checklist: damage profile, burst vs DPS,
tank penetration timing, anti-heal, anti-CC) so a small local model only has
to match labelled pool items against pre-computed directives.
"""
from __future__ import annotations

import json

from sylqon.data import static
from sylqon.data.catalog import Catalog
from sylqon.lcu.lobby import MatchContext


def threat_directives(threat: dict) -> list[str]:
    """Champ-select-time itemization doctrine derived from the enemy comp.
    Tag names in [brackets] match the labels annotated onto pool items."""
    d = []
    if threat.get("heavy_healing"):
        d.append("Heavy enemy healing: pick EXACTLY one [Anti-heal] item.")
    tanks = threat.get("tanks", 0)
    if tanks >= 2:
        d.append(f"{tanks} tanks on enemy team: pick a [% Pen] item and order it "
                 "FIRST among situational picks — penetration must arrive by the "
                 "3rd-4th purchase, before resists stack out of reach.")
    elif tanks == 1:
        d.append("1 tank: a [% Pen] or [%HP Damage] item is a strong later pick.")
    if threat.get("suppression"):
        d.append("Suppression on enemy team: an [Anti-CC] item (QSS/Mercurial) "
                 "is near-mandatory for a carry.")
    elif threat.get("heavy_cc_count", 0) >= 3:
        d.append("3+ heavy-CC enemies: prefer [Anti-CC] / tenacity options.")
    if threat.get("burst_ad") or threat.get("burst_ap"):
        d.append("Assassin/burst threat: include one [Survival] item and order it "
                 "mid-build (2nd situational pick), not last — you must outlive "
                 "the one-shot window before damage matters.")
    if threat.get("physical_threats", 0) >= 4:
        d.append("4+ physical threats: prefer [Armor] when choosing between "
                 "defensive options.")
    if threat.get("magic_threats", 0) >= 3:
        d.append("3+ magic threats: prefer [Magic Resist] when choosing between "
                 "defensive options.")
    if not d:
        d.append("No dominant threat: order situational picks greedily by raw "
                 "damage / powerspike (scaling items first).")
    return d


def rune_directives(threat: dict) -> list[str]:
    """Champ-select-time rune fine-tuning doctrine. The base page is kept; only
    the flexible defensive picks (defense stat shard, secondary defensive runes)
    are nudged toward the resist the enemy comp actually deals."""
    d = []
    ap, ad = threat.get("magic_threats", 0), threat.get("physical_threats", 0)
    if ap >= 3 and ap > ad:
        d.append("Enemy is AP-heavy: lean the defense shard / flexible secondary "
                 "runes toward magic mitigation (Health Scaling shard, Second Wind), "
                 "not armor-flavoured picks.")
    elif ad >= 4 and ad > ap:
        d.append("Enemy is AD-heavy: lean the defense shard / flexible secondary "
                 "runes toward physical mitigation (Bone Plating / Second Wind vs "
                 "pokers).")
    if threat.get("heavy_healing"):
        d.append("Heavy enemy healing: Grievous Wounds comes from items — do NOT "
                 "spend runes on it; keep the damage/utility runes.")
    if not d:
        d.append("No defensive skew: keep the cached/base rune page verbatim.")
    return d


def _tag_label(item: dict) -> str:
    tags = static.ITEM_COUNTER_TAGS.get(item.get("id", 0), ())
    if not tags:
        return ""
    return " [" + "/".join(static.COUNTER_TAG_INFO[t][0] for t in tags) + "]"


def compile_prompt(ctx: MatchContext, candidate: dict, catalog: Catalog) -> str:
    from sylqon import loadout as loadout_mod
    threat = ctx.team_threat_summary()
    a1, a2 = loadout_mod.allowed_spells(candidate, ctx.my_role)
    def_spell1, def_spell2 = loadout_mod.deterministic_spells(candidate, ctx, a1)
    enemy_lines = "\n".join(f"- {e.describe()}" for e in ctx.enemies) or "- unknown (enemy team hidden)"
    ally_lines = "\n".join(f"- {a.describe()}" for a in ctx.allies) or "- none locked yet"
    doctrine_lines = "\n".join(f"- {d}" for d in threat_directives(threat))
    rune_lines = "\n".join(f"- {d}" for d in rune_directives(threat))

    # --- Item sections -------------------------------------------------------
    boots = candidate.get("boots")
    core_items = candidate.get("core_items", [])
    situational_pool = candidate.get("situational_pool", [])
    all_items = candidate.get("items", [])
    # Derive how many situational picks Ollama should make (3 for ADC, 2 otherwise)
    situational_count = max(1, len(all_items) - 1 - len(core_items)) if core_items else 2

    boots_line = (boots or {}).get("name", "unknown")
    core_lines = "\n".join(f"{i+1}. {item['name']}" for i, item in enumerate(core_items))
    pool_lines = "\n".join(
        f"- {item['name']}{_tag_label(item)}: "
        f"{item.get('description') or 'see in-game tooltip'}"
        for item in situational_pool
    ) or "- (no situational options available)"
    item_section = (
        f"ITEM BUILD\n"
        f"Boots (fixed — do NOT include in output): {boots_line}\n\n"
        f"Core items (fixed, output these verbatim unless swapping 1 with a pool item):\n"
        f"{core_lines}\n\n"
        f"Situational item pool — choose EXACTLY {situational_count} for the remaining slots "
        f"(use ONLY names from this list, in purchase order):\n"
        f"{pool_lines}"
    )
    response_schema = {
        "core_items": [f"exactly {len(core_items)} names (default or swap 1 with pool item)"],
        "situational_items": [f"exactly {situational_count} names from situational pool, ordered"],
        "keystone": "exact keystone name",
        "primary_runes": ["3 exact rune names from the keystone's tree"],
        "secondary_style": "one of Precision/Domination/Sorcery/Resolve/Inspiration",
        "secondary_runes": ["2 exact rune names from that tree"],
        "stat_shards": ["offense row pick", "flex row pick", "defense row pick"],
        "spell1": (f"KEEP \"{def_spell1}\" unless strongly justified; "
                   f"if changing, ONLY one of {a1}"),
        "spell2": (f"KEEP \"{def_spell2}\" unless strongly justified; "
                   f"if changing, ONLY one of {a2}"),
        "reasoning": "max 2 sentences",
    }

    return f"""You are a deterministic League of Legends loadout filter. Analyze the enemy threat profile and select the optimal counter-loadout using ONLY the names provided below. Do not invent names.

MY PICK: {ctx.my_champion}, role {ctx.my_role}

MY TEAM (already locked — note their summoners for combo potential):
{ally_lines}

ENEMY TEAM (their summoners change how you trade — e.g. enemy Cleanse/QSS beats your CC, enemy Heal/Barrier shifts all-ins):
{enemy_lines}

TEAM THREAT SUMMARY: {json.dumps(threat)}

TACTICAL DOCTRINE (derived from the enemy comp — these directives override default damage-greedy ordering; [tags] match the labels on pool items):
{doctrine_lines}

RUNE DOCTRINE (keep the base page; only adjust the flexible defensive picks as below):
{rune_lines}

{item_section}

RUNE POOL: keystones {list(static.KEYSTONES)}; minor runes by tree {json.dumps({s: [n for n, t in static.RUNE_STYLE_OF_MINOR.items() if t == s] for s in static.RUNE_STYLES})}

STAT SHARD ROWS: offense {static.SHARD_ROW_OFFENSE}; flex {static.SHARD_ROW_FLEX}; defense {static.SHARD_ROW_DEFENSE}

RULES:
- Apply the TACTICAL DOCTRINE first; fill any remaining slots with the highest-damage pool options.
- situational_items: pick EXACTLY {situational_count} from the pool; order by purchase priority (counters the doctrine marks urgent come first).
- core_items: output unchanged unless 1 swap with a pool item clearly counters a dominant threat.
- SUMMONER SPELLS: these are op.gg's spells for {ctx.my_champion} — keep spell1="{def_spell1}" and spell2="{def_spell2}" by DEFAULT. Only change a spell in a genuinely exceptional case (e.g. Cleanse into chain suppression on a squishy carry), and even then pick ONLY from the op.gg-observed options: spell1 ∈ {a1}, spell2 ∈ {a2}. When unsure, keep the defaults. (For junglers spell1 is locked to Smite and ignored here.)
- Use only exact names that appear in the pools above.

Respond with raw JSON only, exactly this shape:
{json.dumps(response_schema)}"""
