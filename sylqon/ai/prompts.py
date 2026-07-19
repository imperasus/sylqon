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

# Re-exported so existing imports (`from sylqon.ai.prompts import
# rune_pool_for_champion`) keep working while the implementation now lives in
# the seed-driven rune_pool module.
from sylqon.data.rune_pool import rune_pool_for_champion  # noqa: F401
from sylqon.lcu.lobby import MatchContext


def threat_directives(threat: dict) -> list[str]:
    """Champ-select-time itemization doctrine derived from the enemy comp.
    Tag names in [brackets] match the labels annotated onto pool items.

    These directives are also enforced in code (``loadout._enforce_counter_items``):
    a missing mandated tag is swapped into the final build from the situational
    pool, in this same priority order — so the wording here mirrors the
    guarantee rather than merely suggesting it."""
    d = []
    if threat.get("heavy_healing"):
        d.append("Heavy enemy healing: at least one [Anti-heal] item is mandatory "
                 "(enforced) — an early component already cuts the healing.")
    tanks = threat.get("tanks", 0)
    if tanks >= 2:
        d.append(f"{tanks} tanks on enemy team: a [% Pen] item is mandatory; order it "
                 "FIRST among situational picks — penetration must arrive by the "
                 "3rd-4th purchase, before resists stack out of reach.")
    elif tanks == 1:
        d.append("1 tank: a [% Pen] or [%HP Damage] item is a strong later pick.")
    if threat.get("suppression"):
        d.append("Suppression on enemy team: an [Anti-suppression] item (QSS or "
                 "Mercurial Scimitar) is mandatory (enforced) for a carry — "
                 "tenacity, Mercury's Treads and the Cleanse summoner do NOT "
                 "work against suppression.")
    if threat.get("heavy_cc_count", 0) >= 3:
        d.append("3+ heavy-CC enemies: an [Anti-CC] / tenacity option is mandatory "
                 "(enforced).")
    if threat.get("burst_ad") or threat.get("burst_ap"):
        d.append("Assassin/burst threat: one [Survival] item is mandatory (enforced); "
                 "order it mid-build (2nd situational pick), not last — you must "
                 "outlive the one-shot window before damage matters.")
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
    are nudged toward the resist the enemy comp actually deals.

    Enforced in code (``loadout._apply_runes``): the keystone and primary core
    runes are taken from the meta op.gg page and only swapped under a genuinely
    strong threat AND when the swap stays inside the champion's rune pool — the
    AI may only retune the flexible defensive / utility slots and the defense
    stat shard (``loadout._apply_shards``)."""
    d = ["Keep the meta op.gg keystone + primary core; only the flexible "
         "defensive/utility runes and the defense stat shard are adjustable."]
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
    if len(d) == 1:
        d.append("No defensive skew: keep the cached/base rune page verbatim.")
    return d


def _tag_label(item: dict) -> str:
    tags = static.ITEM_COUNTER_TAGS.get(item.get("id", 0), ())
    if not tags:
        return ""
    return " [" + "/".join(static.COUNTER_TAG_INFO[t][0] for t in tags) + "]"


def _spike_label(item: dict) -> str:
    """A purchase-timing hint for non-default spikes, so the model orders early
    game-changers before late scaling."""
    spike = static.ITEM_SPIKE.get(item.get("id", 0))
    if spike == "early":
        return " (spike: EARLY — buy first)"
    if spike == "late":
        return " (spike: LATE — order last)"
    return ""


def compile_prompt(ctx: MatchContext, candidate: dict, catalog: Catalog) -> str:
    from sylqon import loadout as loadout_mod
    from sylqon.analysis import lane_counter
    threat = ctx.team_threat_summary()
    a1, a2 = loadout_mod.allowed_spells(candidate, ctx.my_role)
    def_spell1, def_spell2 = loadout_mod.deterministic_spells(candidate, ctx, a1)
    enemy_lines = "\n".join(f"- {e.describe()}" for e in ctx.enemies) or "- unknown (enemy team hidden)"
    ally_lines = "\n".join(f"- {a.describe()}" for a in ctx.allies) or "- none locked yet"
    doctrine_lines = "\n".join(f"- {d}" for d in threat_directives(threat))
    rune_lines = "\n".join(f"- {d}" for d in rune_directives(threat))
    rune_pool = rune_pool_for_champion(ctx.my_champion)

    # Lane matchup: the direct opponent decides the laning phase — surface
    # them and the first-back plan as their own doctrine block.
    opp = lane_counter.lane_opponent(ctx)
    lane_section = ""
    if opp is not None:
        lane_dir = "\n".join(f"- {d}" for d in lane_counter.lane_directives(ctx))
        fb = ", ".join(i["name"] for i in lane_counter.first_back_items(ctx))
        lane_section = (
            f"\nLANE MATCHUP (your direct opponent — the laning phase is decided here):\n"
            f"- {opp.describe()}\n"
            + (f"{lane_dir}\n" if lane_dir else "")
            + (f"- First-back priorities (already planned): {fb}\n" if fb else "")
        )

    # --- Item sections -------------------------------------------------------
    boots = candidate.get("boots")
    core_items = candidate.get("core_items", [])
    situational_pool = candidate.get("situational_pool", [])
    all_items = candidate.get("items", [])
    # Derive how many situational picks Ollama should make (3 for ADC, 2 otherwise)
    situational_count = max(1, len(all_items) - 1 - len(core_items)) if core_items else 2

    boots_line = (boots or {}).get("name", "unknown")
    core_lines = "\n".join(f"{i+1}. {item['name']}" for i, item in enumerate(core_items))
    if candidate.get("core_reason"):
        # The deterministic selector already swapped the meta combo for this
        # matchup — tell the AI so it builds on it instead of undoing it.
        core_lines += f"\n(matchup-selected core — {candidate['core_reason']}; do NOT swap it back)"
    pool_lines = "\n".join(
        f"- {item['name']}{_tag_label(item)}{_spike_label(item)}: "
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
        "keystone": (
            f"one of {rune_pool['keystone_options']}"
            if rune_pool else "exact keystone name"
        ),
        "primary_runes": (
            [f"exactly 3 names from: {rune_pool['primary_minor_flex']}"]
            if rune_pool else ["3 exact rune names from the keystone's tree"]
        ),
        "secondary_style": (
            f"one of {rune_pool['secondary_style_options']}"
            if rune_pool else "one of Precision/Domination/Sorcery/Resolve/Inspiration"
        ),
        "secondary_runes": (
            [f"exactly 2 names from: {rune_pool['secondary_minor_options']}"]
            if rune_pool else ["2 exact rune names from that tree"]
        ),
        "stat_shards": ["offense row pick", "flex row pick", "defense row pick"],
        "spell1": (f"KEEP \"{def_spell1}\" unless strongly justified; "
                   f"if changing, ONLY one of {a1}"),
        "spell2": (f"KEEP \"{def_spell2}\" unless strongly justified; "
                   f"if changing, ONLY one of {a2}"),
        "reasoning": "max 2 sentences",
    }

    if rune_pool:
        rune_pool_section = (
            f"RUNE POOL (curated for {ctx.my_champion} — use ONLY these names):\n"
            f"  Keystone options (first is meta default): {rune_pool['keystone_options']}\n"
            f"  Primary flexible minor runes (pick exactly 3 from keystone tree, "
            f"these are the allowed options): {rune_pool['primary_minor_flex']}\n"
            f"  Secondary style options: {rune_pool['secondary_style_options']}\n"
            f"  Secondary minor rune options (pick exactly 2): {rune_pool['secondary_minor_options']}"
        )
    else:
        rune_pool_section = (
            f"RUNE POOL: keystones {list(static.KEYSTONES)}; "
            f"minor runes by tree {json.dumps({s: [n for n, t in static.RUNE_STYLE_OF_MINOR.items() if t == s] for s in static.RUNE_STYLES})}"
        )

    return f"""You are a deterministic League of Legends loadout filter. Analyze the enemy threat profile and select the optimal counter-loadout using ONLY the names provided below. Do not invent names.

MY PICK: {ctx.my_champion}, role {ctx.my_role}

MY TEAM (already locked — note their summoners for combo potential):
{ally_lines}

ENEMY TEAM (their summoners change how you trade — e.g. enemy Cleanse/QSS beats your CC, enemy Heal/Barrier shifts all-ins):
{enemy_lines}
{lane_section}
TEAM THREAT SUMMARY: {json.dumps(threat)}

TACTICAL DOCTRINE (derived from the enemy comp — these directives override default damage-greedy ordering; [tags] match the labels on pool items):
{doctrine_lines}

RUNE DOCTRINE (keep the base page; only adjust the flexible defensive picks as below):
{rune_lines}

{item_section}

{rune_pool_section}

STAT SHARD ROWS: offense {static.SHARD_ROW_OFFENSE}; flex {static.SHARD_ROW_FLEX}; defense {static.SHARD_ROW_DEFENSE}

RULES:
- Apply the TACTICAL DOCTRINE first; fill any remaining slots with the highest-damage pool options.
- situational_items: pick EXACTLY {situational_count} from the pool; order by purchase priority (counters the doctrine marks urgent come first).
- core_items: output unchanged unless 1 swap with a pool item clearly counters a dominant threat.
- SUMMONER SPELLS: these are op.gg's spells for {ctx.my_champion} — keep spell1="{def_spell1}" and spell2="{def_spell2}" by DEFAULT. Only change a spell in a genuinely exceptional case (e.g. Cleanse into chain CC on a squishy carry — but NEVER as a suppression answer: Cleanse cannot remove suppression, only the QSS item can), and even then pick ONLY from the op.gg-observed options: spell1 ∈ {a1}, spell2 ∈ {a2}. When unsure, keep the defaults. (For junglers spell1 is locked to Smite and ignored here.)
- Use only exact names that appear in the pools above.

Respond with raw JSON only, exactly this shape:
{json.dumps(response_schema)}"""
