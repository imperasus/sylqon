"""Static game constants: summoner spells, rune perk IDs, stat shards and
champion threat heuristics.

Perk IDs are stable across patches; item IDs are resolved at runtime via
Data Dragon (see catalog.py) so the parser survives item reworks.
"""
from __future__ import annotations

# --- Summoner spells ---------------------------------------------------------
SUMMONER_SPELLS = {
    "Cleanse": 1,
    "Exhaust": 3,
    "Flash": 4,
    "Ghost": 6,
    "Heal": 7,
    "Smite": 11,
    "Teleport": 12,
    "Ignite": 14,
    "Barrier": 21,
}
FLASH_ID = SUMMONER_SPELLS["Flash"]
SPELL_BY_ID = {v: k for k, v in SUMMONER_SPELLS.items()}

# Spell slotting (the client's two summoner slots map to fixed hotkeys):
#   spell1 = D key  -> the "utility"/combat summoner (or Smite for junglers)
#   spell2 = F key  -> the mobility summoner (Flash almost always)
# Smite is jungle-exclusive and always pinned to the D key.
MOBILITY_SPELLS = {"Flash", "Ghost"}
UTILITY_SPELLS = {"Ignite", "Exhaust", "Cleanse", "Barrier", "Heal", "Teleport"}

# spell1 (D key) may only ever come from the utility pool (Smite handled
# separately for junglers); spell2 (F key) only from the mobility pool.
ALLOWED_SPELL1 = ["Ignite", "Exhaust", "Cleanse", "Barrier", "Heal", "Teleport"]
ALLOWED_SPELL2 = ["Flash", "Ghost"]

DEFAULT_SPELL1_BY_ROLE = {       # D key default when the build carries none
    "top": "Teleport",
    "jungle": "Smite",
    "middle": "Ignite",
    "bottom": "Heal",
    "utility": "Exhaust",
}
DEFAULT_SPELL2 = "Flash"          # F key default for every role

# One-line summoner descriptions so the AI (and the dashboard) can reason
# about which spell counters the enemy comp. category drives slotting.
SPELL_INFO: dict[str, tuple[str, str]] = {
    "Flash":    ("Mobility", "Blink a short distance — highest-value summoner; default F-key on every role."),
    "Ghost":    ("Mobility", "Sustained move speed; for champions that kite/chase on foot rather than blink."),
    "Ignite":   ("Utility",  "True-damage DoT + Grievous Wounds; kill pressure and anti-heal in lane."),
    "Exhaust":  ("Utility",  "Slows a target and cuts its damage ~40%; best vs a single fed AD carry / assassin."),
    "Cleanse":  ("Utility",  "Removes most CC and summoner debuffs; vs chain CC on a carry. Does NOT remove suppression (Malzahar/Warwick/Urgot/Skarner R) — only QSS/Mercurial does."),
    "Barrier":  ("Utility",  "Brief self shield; vs burst when you only need to survive one combo."),
    "Heal":     ("Utility",  "Self + ally heal and burst MS; default ADC sustain and 2v2 dueling."),
    "Teleport": ("Utility",  "Global reposition; top-lane map pressure, recoveries and flanks."),
    "Smite":    ("Jungle",   "Jungle pet damage and objective control; mandatory on jungle, fixed to the D key."),
}

# Role-specific starter items auto-added to the shop's opening block. Jungle
# gets its companion pet, support gets the quest item. IDs are what the client
# needs; names are cosmetic (the catalog may not list these as 'completed').
ROLE_STARTER_ITEMS: dict[str, dict] = {
    "jungle":  {"id": 1101, "name": "Scorchclaw Pup"},   # jungle companion
    "utility": {"id": 3865, "name": "World Atlas"},       # support quest item
}

# The three jungle companions are interchangeable openers (op.gg/seed may list
# any of them). Treat ANY as "the jungle starter is already present" so we never
# stack two pets — only one jungle item should ever show.
JUNGLE_COMPANION_IDS: frozenset[int] = frozenset({
    1101,   # Scorchclaw Pup
    1102,   # Gustwalker Hatchling
    1103,   # Mosstomper Seedling
})

# Consumable guaranteed in the opening block so the player always starts with a
# "drink". Health Potion is the universal default; if op.gg already lists any
# opener consumable we keep theirs instead of doubling up.
STARTER_CONSUMABLE: dict = {"id": 2003, "name": "Health Potion"}
STARTER_CONSUMABLE_IDS: frozenset[int] = frozenset({
    2003,   # Health Potion
    2031,   # Refillable Potion
    2033,   # Corrupting Potion
    2010,   # Total Biscuit of Everlasting Will
})

# Defensive boots the matchup-aware selector may inject under a clearly dominant
# enemy threat. Both are universal (fit any role/class), so a smart swap is safe.
MERCURYS_TREADS: dict = {"id": 3111, "name": "Mercury's Treads"}    # vs AP / heavy CC
PLATED_STEELCAPS: dict = {"id": 3047, "name": "Plated Steelcaps"}   # vs AD / auto-attackers

# Consumables surfaced as the final item-set block ("buy on backs"). The
# Control Ward is non-negotiable macro discipline on every role; the elixir is
# matched to the build's damage class once the player hits 3+ items.
CONTROL_WARD: dict = {"id": 2055, "name": "Control Ward"}
ELIXIR_OF_IRON: dict = {"id": 2138, "name": "Elixir of Iron"}       # tanks / hybrids
ELIXIR_OF_SORCERY: dict = {"id": 2139, "name": "Elixir of Sorcery"}  # AP builds
ELIXIR_OF_WRATH: dict = {"id": 2140, "name": "Elixir of Wrath"}      # AD builds
# Smart-swap thresholds: only override op.gg's meta boot when the threat is
# clearly dominant, so we never over-build defence into a balanced comp.
BOOT_SWAP_AP_CC_MIN = 3   # >=3 AP threats OR >=3 heavy-CC enemies -> Mercury's
BOOT_SWAP_AD_MIN = 4      # >=4 AD threats -> Plated Steelcaps

# --- Rune styles -------------------------------------------------------------
RUNE_STYLES = {
    "Precision": 8000,
    "Domination": 8100,
    "Sorcery": 8200,
    "Resolve": 8400,
    "Inspiration": 8300,
}

KEYSTONES = {
    "Press the Attack": 8005,
    "Lethal Tempo": 8008,
    "Fleet Footwork": 8021,
    "Conqueror": 8010,
    "Electrocute": 8112,
    "Dark Harvest": 8128,
    "Hail of Blades": 9923,
    "Summon Aery": 8214,
    "Arcane Comet": 8229,
    "Phase Rush": 8230,
    "Grasp of the Undying": 8437,
    "Aftershock": 8439,
    "Guardian": 8465,
    "Glacial Augment": 8351,
    "Unsealed Spellbook": 8360,
    "First Strike": 8369,
}

MINOR_RUNES = {
    # Precision
    "Triumph": 9111,
    "Presence of Mind": 8009,
    "Legend: Alacrity": 9104,
    "Legend: Haste": 9105,
    "Legend: Bloodline": 9103,
    "Coup de Grace": 8014,
    "Cut Down": 8017,
    "Last Stand": 8299,
    "Absorb Life": 9101,
    # Domination
    "Cheap Shot": 8126,
    "Taste of Blood": 8139,
    "Sudden Impact": 8143,
    "Eyeball Collection": 8120,
    "Ghost Poro": 8136,
    "Zombie Ward": 8138,
    "Treasure Hunter": 8135,
    "Relentless Hunter": 8105,
    "Ultimate Hunter": 8106,
    "Grisly Mementos": 8140,
    "Sixth Sense": 8137,
    "Deep Ward": 8141,
    # Sorcery
    "Nullifying Orb": 8224,
    "Manaflow Band": 8226,
    "Nimbus Cloak": 8275,
    "Transcendence": 8210,
    "Celerity": 8234,
    "Absolute Focus": 8233,
    "Scorch": 8237,
    "Waterwalking": 8232,
    "Gathering Storm": 8236,
    # Resolve
    "Demolish": 8446,
    "Font of Life": 8463,
    "Shield Bash": 8401,
    "Conditioning": 8429,
    "Second Wind": 8444,
    "Bone Plating": 8473,
    "Overgrowth": 8451,
    "Revitalize": 8453,
    "Unflinching": 8242,
    # Inspiration
    "Hextech Flashtraption": 8306,
    "Magical Footwear": 8304,
    "Triple Tonic": 8313,
    "Future's Market": 8321,
    "Minion Dematerializer": 8316,
    "Biscuit Delivery": 8345,
    "Cosmic Insight": 8347,
    "Approach Velocity": 8410,
    "Time Warp Tonic": 8352,
}

ALL_RUNES = {**KEYSTONES, **MINOR_RUNES}

KEYSTONE_STYLE = {
    "Press the Attack": "Precision", "Lethal Tempo": "Precision",
    "Fleet Footwork": "Precision", "Conqueror": "Precision",
    "Electrocute": "Domination", "Dark Harvest": "Domination",
    "Hail of Blades": "Domination",
    "Summon Aery": "Sorcery", "Arcane Comet": "Sorcery", "Phase Rush": "Sorcery",
    "Grasp of the Undying": "Resolve", "Aftershock": "Resolve", "Guardian": "Resolve",
    "Glacial Augment": "Inspiration", "Unsealed Spellbook": "Inspiration",
    "First Strike": "Inspiration",
}

# Per-champion rune archetype: the keystones op.gg actually runs on this
# champion and the flexible minor-rune slots the AI may adjust.
# Structure per entry:
#   "keystone_options": list[str]  — first item is the meta default
#   "primary_minor_flex": list[str] — row 2+3 minor rune names the AI may pick from
#                                     (row 1 / slot 1 is typically fixed per keystone)
#   "secondary_style_options": list[str] — trees op.gg uses as secondary
#   "secondary_minor_options": list[str] — minor runes from those trees the AI may use
# If a champion is absent from this dict, the system falls back to the full
# global rune pool (current behavior, unchanged).
CHAMPION_RUNE_ARCHETYPES: dict[str, dict] = {
    # ADC
    "Jinx": {
        "keystone_options": ["Lethal Tempo", "Fleet Footwork"],
        "primary_minor_flex": ["Triumph", "Presence of Mind", "Legend: Alacrity", "Legend: Bloodline", "Coup de Grace", "Cut Down", "Last Stand"],
        "secondary_style_options": ["Domination", "Sorcery", "Resolve"],
        "secondary_minor_options": ["Taste of Blood", "Treasure Hunter", "Eyeball Collection", "Absolute Focus", "Gathering Storm", "Bone Plating", "Second Wind"],
    },
    "Caitlyn": {
        "keystone_options": ["Lethal Tempo", "Fleet Footwork"],
        "primary_minor_flex": ["Triumph", "Presence of Mind", "Legend: Alacrity", "Legend: Bloodline", "Coup de Grace", "Cut Down"],
        "secondary_style_options": ["Domination", "Inspiration", "Sorcery"],
        "secondary_minor_options": ["Taste of Blood", "Eyeball Collection", "Treasure Hunter", "Magical Footwear", "Biscuit Delivery", "Manaflow Band", "Absolute Focus"],
    },
    "Kai'Sa": {
        "keystone_options": ["Press the Attack", "Lethal Tempo"],
        "primary_minor_flex": ["Triumph", "Legend: Alacrity", "Legend: Bloodline", "Coup de Grace", "Cut Down"],
        "secondary_style_options": ["Domination", "Sorcery", "Resolve"],
        "secondary_minor_options": ["Taste of Blood", "Eyeball Collection", "Treasure Hunter", "Absolute Focus", "Gathering Storm", "Bone Plating"],
    },
    "Jhin": {
        "keystone_options": ["Fleet Footwork", "Lethal Tempo"],
        "primary_minor_flex": ["Triumph", "Presence of Mind", "Legend: Alacrity", "Legend: Bloodline", "Coup de Grace", "Cut Down", "Last Stand"],
        "secondary_style_options": ["Sorcery", "Domination", "Resolve"],
        "secondary_minor_options": ["Manaflow Band", "Absolute Focus", "Gathering Storm", "Taste of Blood", "Eyeball Collection", "Bone Plating", "Second Wind"],
    },
    "Ezreal": {
        "keystone_options": ["Fleet Footwork", "Conqueror"],
        "primary_minor_flex": ["Triumph", "Presence of Mind", "Legend: Alacrity", "Legend: Haste", "Coup de Grace", "Last Stand"],
        "secondary_style_options": ["Sorcery", "Inspiration", "Domination"],
        "secondary_minor_options": ["Manaflow Band", "Absolute Focus", "Gathering Storm", "Magical Footwear", "Biscuit Delivery", "Taste of Blood"],
    },
    "Ashe": {
        "keystone_options": ["Fleet Footwork", "Lethal Tempo"],
        "primary_minor_flex": ["Triumph", "Presence of Mind", "Legend: Alacrity", "Legend: Bloodline", "Coup de Grace", "Cut Down", "Last Stand"],
        "secondary_style_options": ["Domination", "Sorcery", "Resolve"],
        "secondary_minor_options": ["Taste of Blood", "Eyeball Collection", "Treasure Hunter", "Absolute Focus", "Bone Plating", "Second Wind"],
    },
    # Mid
    "Zed": {
        "keystone_options": ["Electrocute", "Dark Harvest"],
        "primary_minor_flex": ["Cheap Shot", "Taste of Blood", "Eyeball Collection", "Ghost Poro", "Treasure Hunter", "Relentless Hunter", "Ultimate Hunter"],
        "secondary_style_options": ["Precision", "Sorcery", "Inspiration"],
        "secondary_minor_options": ["Triumph", "Coup de Grace", "Legend: Alacrity", "Absolute Focus", "Gathering Storm", "Magical Footwear"],
    },
    "Ahri": {
        "keystone_options": ["Electrocute", "Dark Harvest", "Phase Rush"],
        "primary_minor_flex": ["Cheap Shot", "Taste of Blood", "Eyeball Collection", "Ghost Poro", "Treasure Hunter", "Relentless Hunter", "Ultimate Hunter"],
        "secondary_style_options": ["Sorcery", "Inspiration", "Precision"],
        "secondary_minor_options": ["Manaflow Band", "Transcendence", "Gathering Storm", "Magical Footwear", "Biscuit Delivery", "Triumph"],
    },
    "Syndra": {
        "keystone_options": ["Electrocute", "Arcane Comet"],
        "primary_minor_flex": ["Cheap Shot", "Taste of Blood", "Eyeball Collection", "Treasure Hunter", "Ultimate Hunter", "Relentless Hunter"],
        "secondary_style_options": ["Sorcery", "Inspiration"],
        "secondary_minor_options": ["Manaflow Band", "Transcendence", "Absolute Focus", "Gathering Storm", "Magical Footwear", "Biscuit Delivery"],
    },
    "LeBlanc": {
        "keystone_options": ["Electrocute", "Dark Harvest"],
        "primary_minor_flex": ["Cheap Shot", "Taste of Blood", "Eyeball Collection", "Treasure Hunter", "Relentless Hunter", "Ultimate Hunter"],
        "secondary_style_options": ["Sorcery", "Inspiration", "Precision"],
        "secondary_minor_options": ["Manaflow Band", "Absolute Focus", "Gathering Storm", "Magical Footwear", "Biscuit Delivery"],
    },
    # Top
    "Darius": {
        "keystone_options": ["Conqueror", "Grasp of the Undying"],
        "primary_minor_flex": ["Triumph", "Presence of Mind", "Legend: Alacrity", "Legend: Haste", "Coup de Grace", "Last Stand"],
        "secondary_style_options": ["Domination", "Resolve", "Sorcery"],
        "secondary_minor_options": ["Taste of Blood", "Eyeball Collection", "Treasure Hunter", "Bone Plating", "Second Wind", "Conditioning", "Transcendence"],
    },
    "Garen": {
        "keystone_options": ["Conqueror", "Grasp of the Undying"],
        "primary_minor_flex": ["Triumph", "Legend: Alacrity", "Legend: Haste", "Coup de Grace", "Last Stand"],
        "secondary_style_options": ["Resolve", "Domination", "Inspiration"],
        "secondary_minor_options": ["Bone Plating", "Second Wind", "Conditioning", "Overgrowth", "Demolish", "Magical Footwear"],
    },
    "Aatrox": {
        "keystone_options": ["Conqueror"],
        "primary_minor_flex": ["Triumph", "Legend: Alacrity", "Legend: Haste", "Coup de Grace", "Last Stand"],
        "secondary_style_options": ["Domination", "Resolve", "Sorcery"],
        "secondary_minor_options": ["Taste of Blood", "Eyeball Collection", "Treasure Hunter", "Bone Plating", "Second Wind", "Gathering Storm"],
    },
    # Jungle
    "Vi": {
        "keystone_options": ["Conqueror", "Dark Harvest"],
        "primary_minor_flex": ["Triumph", "Legend: Alacrity", "Legend: Haste", "Coup de Grace", "Last Stand"],
        "secondary_style_options": ["Domination", "Resolve", "Sorcery"],
        "secondary_minor_options": ["Taste of Blood", "Treasure Hunter", "Bone Plating", "Second Wind", "Gathering Storm"],
    },
    "Kayn": {
        "keystone_options": ["Conqueror", "Dark Harvest", "Electrocute"],
        "primary_minor_flex": ["Triumph", "Legend: Alacrity", "Coup de Grace", "Taste of Blood", "Eyeball Collection", "Treasure Hunter"],
        "secondary_style_options": ["Domination", "Precision", "Resolve"],
        "secondary_minor_options": ["Eyeball Collection", "Treasure Hunter", "Legend: Alacrity", "Triumph", "Bone Plating", "Second Wind"],
    },
    # Support
    "Thresh": {
        "keystone_options": ["Aftershock", "Glacial Augment"],
        "primary_minor_flex": ["Font of Life", "Shield Bash", "Bone Plating", "Second Wind", "Conditioning", "Overgrowth", "Unflinching"],
        "secondary_style_options": ["Inspiration", "Domination", "Precision"],
        "secondary_minor_options": ["Magical Footwear", "Biscuit Delivery", "Cosmic Insight", "Eyeball Collection", "Treasure Hunter", "Triumph"],
    },
    "Nautilus": {
        "keystone_options": ["Aftershock", "Guardian"],
        "primary_minor_flex": ["Font of Life", "Shield Bash", "Bone Plating", "Second Wind", "Conditioning", "Overgrowth", "Unflinching"],
        "secondary_style_options": ["Inspiration", "Domination", "Precision"],
        "secondary_minor_options": ["Magical Footwear", "Biscuit Delivery", "Cosmic Insight", "Eyeball Collection", "Treasure Hunter"],
    },
    "Soraka": {
        "keystone_options": ["Summon Aery", "Arcane Comet"],
        "primary_minor_flex": ["Manaflow Band", "Nimbus Cloak", "Transcendence", "Celerity", "Absolute Focus", "Gathering Storm"],
        "secondary_style_options": ["Resolve", "Inspiration", "Precision"],
        "secondary_minor_options": ["Revitalize", "Bone Plating", "Second Wind", "Font of Life", "Magical Footwear", "Biscuit Delivery", "Triumph"],
    },
}

RUNE_STYLE_OF_MINOR = {
    name: style
    for style, names in {
        "Precision": ["Triumph", "Presence of Mind", "Legend: Alacrity", "Legend: Haste",
                      "Legend: Bloodline", "Coup de Grace", "Cut Down", "Last Stand",
                      "Absorb Life"],
        "Domination": ["Cheap Shot", "Taste of Blood", "Sudden Impact", "Eyeball Collection",
                       "Ghost Poro", "Zombie Ward", "Treasure Hunter", "Relentless Hunter",
                       "Ultimate Hunter", "Grisly Mementos", "Sixth Sense", "Deep Ward"],
        "Sorcery": ["Nullifying Orb", "Manaflow Band", "Nimbus Cloak", "Transcendence",
                    "Celerity", "Absolute Focus", "Scorch", "Waterwalking", "Gathering Storm"],
        "Resolve": ["Demolish", "Font of Life", "Shield Bash", "Conditioning", "Second Wind",
                    "Bone Plating", "Overgrowth", "Revitalize", "Unflinching"],
        "Inspiration": ["Hextech Flashtraption", "Magical Footwear", "Triple Tonic",
                        "Future's Market", "Minion Dematerializer", "Biscuit Delivery",
                        "Cosmic Insight", "Approach Velocity", "Time Warp Tonic"],
    }.items()
    for name in names
}

# --- Stat shards ---------------------------------------------------------------
# Row 1 = offense, row 2 = flex, row 3 = defense.
STAT_SHARDS = {
    "Adaptive Force": 5008,
    "Attack Speed": 5005,
    "Ability Haste": 5007,
    "Move Speed": 5010,
    "Health Scaling": 5001,
    "Health": 5011,
    "Tenacity and Slow Resist": 5013,
}
SHARD_ROW_OFFENSE = ["Adaptive Force", "Attack Speed", "Ability Haste"]
SHARD_ROW_FLEX = ["Adaptive Force", "Move Speed", "Health Scaling"]
SHARD_ROW_DEFENSE = ["Health", "Tenacity and Slow Resist", "Health Scaling"]
SHARD_ID_SET = set(STAT_SHARDS.values())
SHARD_BY_ID = {v: k for k, v in STAT_SHARDS.items()}

DEFAULT_SHARDS = ["Adaptive Force", "Adaptive Force", "Health"]

# Reverse lookup maps (id → name) for OP.GG MCP integration
RUNE_BY_ID = {v: k for k, v in ALL_RUNES.items()}
STYLE_BY_ID = {v: k for k, v in RUNE_STYLES.items()}

# --- Champion threat heuristics -------------------------------------------------
# Used to compile enemy profiles; damage type comes from Data Dragon info
# scores, these sets flag qualitative threats the AI weighs.
HEAVY_CC_CHAMPS = {
    "Malzahar", "Warwick", "Skarner", "Urgot", "Mordekaiser", "Tahm Kench",
    "Leona", "Nautilus", "Thresh", "Morgana", "Lux", "Zoe", "Lissandra",
    "Sejuani", "Maokai", "Amumu", "Rammus", "Ashe", "Varus",
    "Twisted Fate", "Pantheon", "Renata Glasc", "Rell", "Alistar", "Braum",
    "Veigar", "Annie", "Neeko", "Ornn", "Cho'Gath", "Sion", "Poppy", "Zac",
}
# True suppression / point-click lockdown that a QSS / Mercurial CAN cleanse and
# that effectively neutralises a carry. Mordekaiser (R is a banish/isolation, not
# removable by QSS) and post-rework Tahm Kench (no offensive devour) were removed
# — neither is a real suppression, so neither should force the near-mandatory
# anti-CC directive. Urgot's R applies a true suppression that QSS clears.
SUPPRESSION_CHAMPS = {"Malzahar", "Warwick", "Skarner", "Urgot"}
HIGH_BURST_AD = {
    "Zed", "Talon", "Qiyana", "Rengar", "Kha'Zix", "Naafiri", "Pyke",
    "Nocturne", "Kayn", "Briar", "Pantheon",
}
HIGH_BURST_AP = {
    "Syndra", "LeBlanc", "Annie", "Veigar", "Fizz", "Akali", "Evelynn",
    "Lissandra", "Zoe", "Sylas", "Diana", "Vex", "Hwei", "Aurora",
}
HEAVY_HEALING = {
    "Soraka", "Aatrox", "Dr. Mundo", "Vladimir", "Sylas", "Swain", "Yuumi",
    "Sona", "Nami", "Warwick", "Fiora", "Illaoi", "Briar", "Zac", "Maokai",
    "Kayn", "Olaf", "Trundle",
}
HEAVY_POKE = {
    "Xerath", "Vel'Koz", "Ziggs", "Lux", "Jayce", "Zoe", "Varus", "Ezreal",
    "Caitlyn", "Jhin", "Nidalee", "Karma", "Hwei",
}
HEAVY_TANK = {
    "Ornn", "Sion", "Malphite", "Rammus", "Zac", "Sejuani", "Cho'Gath",
    "Dr. Mundo", "Tahm Kench", "Shen", "K'Sante", "Maokai", "Amumu",
}
# Champions whose strongest win condition is 1-v-1 side-lane pressure. Used by
# the draft comp classifier to flag a split-push archetype.
SPLIT_PUSH_CHAMPS = {
    "Fiora", "Jax", "Camille", "Tryndamere", "Yorick", "Trundle", "Nasus",
    "Sion", "Shen", "Gangplank", "Quinn", "Kayle",
    "Illaoi", "Riven", "Aatrox", "Renekton", "Yone", "Jayce",
}

# --- Champion / item damage typing (counter-item eligibility) -----------------
# The damage profile a champion actually BUILDS for ("ad" / "ap" / "mixed").
# Used to keep counter-item enforcement type-correct: never slot an AP item on a
# pure-AD carry (e.g. Lord Dominik's on Syndra) or an AD item on an AP mage
# (e.g. Morellonomicon on Zed). "mixed" is the permissive fallback — the right
# call for true hybrids, tanks and supports, whose relevant counter items are
# universal anyway. Champions absent here fall back to "mixed".
CHAMPION_DAMAGE_TYPE: dict[str, str] = {
    # --- AD: marksmen ---
    "Jinx": "ad", "Caitlyn": "ad", "Kai'Sa": "ad", "Jhin": "ad", "Ezreal": "ad",
    "Ashe": "ad", "Miss Fortune": "ad", "Smolder": "ad", "Kog'Maw": "ad",
    "Lucian": "ad", "Tristana": "ad", "Samira": "ad", "Xayah": "ad", "Draven": "ad",
    "Sivir": "ad", "Vayne": "ad", "Aphelios": "ad", "Zeri": "ad", "Nilah": "ad",
    "Varus": "ad", "Twitch": "ad", "Quinn": "ad", "Kalista": "ad",
    # --- AD: assassins ---
    "Zed": "ad", "Talon": "ad", "Qiyana": "ad", "Rengar": "ad", "Kha'Zix": "ad",
    "Naafiri": "ad", "Pyke": "ad", "Nocturne": "ad", "Kayn": "ad",
    # --- AD: fighters / bruisers ---
    "Darius": "ad", "Garen": "ad", "Aatrox": "ad", "Renekton": "ad", "Riven": "ad",
    "Camille": "ad", "Fiora": "ad", "Sett": "ad", "Tryndamere": "ad", "Yasuo": "ad",
    "Yone": "ad", "Olaf": "ad", "Trundle": "ad", "Nasus": "ad", "Gnar": "ad",
    "Wukong": "ad", "Pantheon": "ad", "Jayce": "ad", "Gangplank": "ad",
    "Irelia": "ad", "Urgot": "ad", "Illaoi": "ad", "Kled": "ad", "K'Sante": "ad",
    # --- AD: junglers ---
    "Vi": "ad", "Lee Sin": "ad", "Graves": "ad", "Master Yi": "ad", "Hecarim": "ad",
    "Xin Zhao": "ad", "Kindred": "ad", "Viego": "ad", "Briar": "ad",
    # --- AP: mages / assassins ---
    "Hwei": "ap", "Brand": "ap", "Syndra": "ap", "LeBlanc": "ap", "Ahri": "ap",
    "Annie": "ap", "Veigar": "ap", "Fizz": "ap", "Akali": "ap", "Evelynn": "ap",
    "Lissandra": "ap", "Zoe": "ap", "Diana": "ap", "Vex": "ap", "Aurora": "ap",
    "Xerath": "ap", "Vel'Koz": "ap", "Ziggs": "ap", "Lux": "ap", "Orianna": "ap",
    "Viktor": "ap", "Cassiopeia": "ap", "Karthus": "ap", "Anivia": "ap",
    "Swain": "ap", "Vladimir": "ap", "Ryze": "ap", "Taliyah": "ap", "Neeko": "ap",
    "Zyra": "ap", "Seraphine": "ap", "Heimerdinger": "ap", "Malzahar": "ap",
    "Morgana": "ap", "Elise": "ap", "Fiddlesticks": "ap", "Lillia": "ap",
    "Ekko": "ap", "Katarina": "ap", "Kassadin": "ap", "Aurelion Sol": "ap",
    "Mordekaiser": "ap", "Amumu": "ap", "Galio": "ap", "Maokai": "ap",
    "Nidalee": "ap", "Rumble": "ap", "Singed": "ap", "Sylas": "ap",
    # --- AP: enchanters / supports ---
    "Soraka": "ap", "Nami": "ap", "Sona": "ap", "Lulu": "ap", "Janna": "ap",
    "Yuumi": "ap", "Karma": "ap", "Renata Glasc": "ap",
    # --- mixed: hybrids / tanks / utility (their counter items are universal) ---
    "Jax": "mixed", "Kayle": "mixed", "Teemo": "mixed", "Warwick": "mixed",
    "Skarner": "mixed", "Cho'Gath": "mixed", "Malphite": "mixed", "Volibear": "mixed",
    "Udyr": "mixed", "Thresh": "mixed", "Nautilus": "mixed", "Leona": "mixed",
    "Alistar": "mixed", "Braum": "mixed", "Rell": "mixed", "Rakan": "mixed",
    "Blitzcrank": "mixed", "Sejuani": "mixed", "Zac": "mixed", "Ornn": "mixed",
    "Sion": "mixed", "Shen": "mixed", "Tahm Kench": "mixed", "Rammus": "mixed",
    "Poppy": "mixed", "Dr. Mundo": "mixed",
}

ROLE_ALIASES = {
    "top": "top", "jungle": "jungle", "middle": "middle", "mid": "middle",
    "bottom": "bottom", "adc": "bottom", "bot": "bottom",
    "utility": "utility", "support": "utility", "sup": "utility",
}

# --- Ability max-order fallback ------------------------------------------------
# Standard skill MAX priority (which basic ability to rank up first → second →
# third); R is always taken on cooldown and is omitted. Display-only guidance,
# always OVERRIDDEN by op.gg's skill order when the build carries one
# (``build['skill_order']``). Champions absent here simply show no skill panel.
SKILL_MAX_ORDER: dict[str, list[str]] = {
    # Top
    "Darius": ["Q", "W", "E"], "Garen": ["E", "Q", "W"], "Fiora": ["Q", "E", "W"],
    "Camille": ["Q", "W", "E"], "Aatrox": ["Q", "W", "E"], "Riven": ["Q", "W", "E"],
    "Sett": ["W", "E", "Q"], "Mordekaiser": ["Q", "E", "W"], "Renekton": ["Q", "W", "E"],
    "Malphite": ["E", "Q", "W"], "Ornn": ["Q", "W", "E"], "Shen": ["Q", "E", "W"],
    "Nasus": ["Q", "W", "E"], "Jax": ["W", "Q", "E"], "Gnar": ["Q", "E", "W"],
    "Teemo": ["E", "Q", "W"], "K'Sante": ["Q", "W", "E"],
    # Jungle
    "Lee Sin": ["Q", "E", "W"], "Vi": ["Q", "E", "W"], "Hecarim": ["Q", "E", "W"],
    "Graves": ["Q", "E", "W"], "Kha'Zix": ["Q", "E", "W"], "Warwick": ["Q", "W", "E"],
    "Master Yi": ["Q", "E", "W"], "Kayn": ["Q", "E", "W"], "Viego": ["Q", "E", "W"],
    "Amumu": ["Q", "E", "W"], "Sejuani": ["W", "E", "Q"], "Nocturne": ["Q", "E", "W"],
    # Mid
    "Ahri": ["Q", "W", "E"], "Zed": ["Q", "E", "W"], "Yasuo": ["Q", "E", "W"],
    "Syndra": ["Q", "E", "W"], "Orianna": ["Q", "W", "E"], "Katarina": ["Q", "E", "W"],
    "Akali": ["Q", "E", "W"], "LeBlanc": ["Q", "E", "W"], "Lux": ["E", "Q", "W"],
    "Annie": ["Q", "W", "E"], "Viktor": ["Q", "E", "W"], "Vex": ["Q", "E", "W"],
    "Sylas": ["Q", "E", "W"], "Talon": ["Q", "W", "E"], "Veigar": ["Q", "W", "E"],
    # Bot
    "Jinx": ["Q", "W", "E"], "Caitlyn": ["Q", "W", "E"], "Jhin": ["Q", "W", "E"],
    "Kai'Sa": ["Q", "W", "E"], "Ezreal": ["Q", "W", "E"], "Ashe": ["W", "Q", "E"],
    "Lucian": ["Q", "E", "W"], "Tristana": ["E", "Q", "W"], "Samira": ["Q", "W", "E"],
    "Xayah": ["Q", "E", "W"], "Draven": ["Q", "W", "E"], "Sivir": ["W", "Q", "E"],
    "Miss Fortune": ["Q", "W", "E"], "Vayne": ["Q", "W", "E"], "Aphelios": ["Q", "W", "E"],
    # Support
    "Thresh": ["Q", "E", "W"], "Leona": ["E", "W", "Q"], "Nautilus": ["Q", "E", "W"],
    "Lulu": ["E", "Q", "W"], "Nami": ["W", "E", "Q"], "Soraka": ["Q", "E", "W"],
    "Pyke": ["Q", "W", "E"], "Morgana": ["Q", "W", "E"], "Karma": ["Q", "E", "W"],
    "Yuumi": ["Q", "E", "W"], "Rakan": ["W", "E", "Q"], "Blitzcrank": ["Q", "E", "W"],
}

# --- Item counter heuristics ---------------------------------------------------
# Maps completed-item IDs to the tactical purpose(s) they serve. First tag is
# the primary purpose. Used to annotate the AI prompt's situational pool and to
# label alternative blocks in the injected item set, so the player can re-route
# mid-game ("2 tanks got fed -> grab the % pen block").
ITEM_COUNTER_TAGS: dict[int, tuple[str, ...]] = {
    # Grievous Wounds (anti-heal)
    3033: ("anti_heal", "percent_pen"),   # Mortal Reminder
    3165: ("anti_heal",),                 # Morellonomicon
    6609: ("anti_heal",),                 # Chempunk Chainsword
    3075: ("anti_heal", "armor"),         # Thornmail
    # % / flat resist penetration (vs tanks, stacked resists)
    3036: ("percent_pen",),               # Lord Dominik's Regards
    6694: ("percent_pen",),               # Serylda's Grudge
    3135: ("percent_pen",),               # Void Staff
    3137: ("percent_pen",),               # Cryptbloom
    3302: ("percent_pen",),               # Terminus
    3071: ("percent_pen",),               # Black Cleaver
    # %HP / sustained damage vs high-HP frontline
    3153: ("tank_shred",),                # Blade of The Ruined King
    6653: ("tank_shred",),                # Liandry's Torment
    3124: ("tank_shred",),                # Guinsoo's Rageblade
    6610: ("tank_shred",),                # Sundered Sky
    # Anti-burst / survival
    3026: ("anti_burst",),                # Guardian Angel
    3157: ("anti_burst",),                # Zhonya's Hourglass
    3156: ("anti_burst", "mr"),           # Maw of Malmortius
    3102: ("anti_burst", "mr"),           # Banshee's Veil
    3814: ("anti_burst",),                # Edge of Night
    6333: ("anti_burst", "armor"),        # Death's Dance
    3053: ("anti_burst",),                # Sterak's Gage
    6673: ("anti_burst",),                # Immortal Shieldbow
    # On-demand CC removal vs suppression / chain CC. Only QSS/Mercurial's
    # active removes suppression — tenacity (Mercs) and Mikael's do not, hence
    # the narrower anti_suppression tag on exactly those two.
    3140: ("anti_cc", "anti_suppression"),        # Quicksilver Sash
    3139: ("anti_cc", "anti_suppression", "mr"),  # Mercurial Scimitar
    3111: ("anti_cc", "mr"),              # Mercury's Treads
    3222: ("anti_cc",),                   # Mikael's Blessing
    # Magic resist (vs AP-heavy comps)
    3091: ("mr", "tank_shred"),           # Wit's End
    6665: ("mr", "armor"),                # Jak'Sho, The Protean
    3065: ("mr",),                        # Spirit Visage
    4401: ("mr",),                        # Force of Nature
    # Armor (vs AD-heavy comps)
    3742: ("armor",),                     # Dead Man's Plate
    3143: ("armor",),                     # Randuin's Omen
    3110: ("armor",),                     # Frozen Heart
    3047: ("armor",),                     # Plated Steelcaps
    # Anti-shield
    6695: ("anti_shield",),               # Serpent's Fang
    # Mobility / kiting
    3046: ("mobility",),                  # Phantom Dancer
    4629: ("mobility",),                  # Cosmic Drive
    # OpenBuild additions
    3161: ("tank_shred", "percent_pen"),  # Spear of Shojin
    3094: ("mobility",),                  # Rapid Firecannon
    6662: ("anti_burst", "armor"),        # Iceborn Gauntlet
}

# tag -> (short label, when-to-buy guidance). Dict order doubles as display
# priority for the alternative blocks in the item set. Keep the strings short:
# they end up in LCU block titles and the whole item-set collection must stay
# under the client's 64KB body limit.
COUNTER_TAG_INFO: dict[str, tuple[str, str]] = {
    "anti_heal":   ("Anti-heal", "vs heavy healing — early component is enough"),
    "percent_pen": ("% Pen", "vs 2+ tanks — buy 3rd-4th item"),
    "anti_cc":     ("Anti-CC", "vs chain CC — tenacity / on-demand cleanse"),
    "anti_suppression": ("Anti-suppression", "QSS/Mercurial active — the ONLY answer to suppression"),
    "anti_burst":  ("Survival", "vs assassins / burst"),
    "mr":          ("Magic Resist", "vs fed AP / 3+ AP threats"),
    "armor":       ("Armor", "vs fed AD / 4+ AD threats"),
    "tank_shred":  ("%HP Damage", "vs high-HP frontline in long fights"),
    "anti_shield": ("Anti-shield", "vs shield stacking"),
    "mobility":    ("Mobility", "extra MS for kiting / positioning"),
    "damage":      ("Damage / Greed", "when ahead or no dominant threat"),
}

# Item damage-class restriction, keyed by Data Dragon item NAME:
#   "ad_only"   — scales with / itemises AD (lethality, armor pen, crit, AD on-hit)
#   "ap_only"   — scales with / itemises AP (ability power)
#   "universal" — resists / HP / tenacity / revive / cleanse — damage-agnostic
# Consumed by ``loadout._item_eligible_for_champion`` to gate counter items (and
# AI item picks) against the champion's CHAMPION_DAMAGE_TYPE. Items absent here
# fall back to "universal" (permissive) so a missing entry never over-restricts.
ITEM_CLASS_RESTRICTION: dict[str, str] = {
    # --- AD-only (lethality / armor pen / crit / AD on-hit) ---
    "Mortal Reminder": "ad_only",
    "Chempunk Chainsword": "ad_only",
    "Lord Dominik's Regards": "ad_only",
    "Serylda's Grudge": "ad_only",
    "Black Cleaver": "ad_only",
    "Terminus": "ad_only",
    "Blade of The Ruined King": "ad_only",
    "Sundered Sky": "ad_only",
    "Maw of Malmortius": "ad_only",
    "Edge of Night": "ad_only",
    "Death's Dance": "ad_only",
    "Immortal Shieldbow": "ad_only",
    "Mercurial Scimitar": "ad_only",
    "Serpent's Fang": "ad_only",
    "Phantom Dancer": "ad_only",
    "Rapid Firecannon": "ad_only",
    "Umbral Glaive": "ad_only",
    "Spear of Shojin": "ad_only",
    "Infinity Edge": "ad_only",
    "Kraken Slayer": "ad_only",
    "Bloodthirster": "ad_only",
    "Essence Reaver": "ad_only",
    "The Collector": "ad_only",
    "Runaan's Hurricane": "ad_only",
    "Ravenous Hydra": "ad_only",
    "Trinity Force": "ad_only",
    "Stridebreaker": "ad_only",
    "Experimental Hexplate": "ad_only",
    "Youmuu's Ghostblade": "ad_only",
    "Eclipse": "ad_only",
    "Hubris": "ad_only",
    "Voltaic Cyclosword": "ad_only",
    # --- AP-only (ability power scaling) ---
    "Morellonomicon": "ap_only",
    "Void Staff": "ap_only",
    "Cryptbloom": "ap_only",
    "Liandry's Torment": "ap_only",
    "Zhonya's Hourglass": "ap_only",
    "Banshee's Veil": "ap_only",
    "Mikael's Blessing": "ap_only",
    "Cosmic Drive": "ap_only",
    "Rabadon's Deathcap": "ap_only",
    "Luden's Echo": "ap_only",
    "Shadowflame": "ap_only",
    "Blackfire Torch": "ap_only",
    "Rylai's Crystal Scepter": "ap_only",
    "Lich Bane": "ap_only",
    "Nashor's Tooth": "ap_only",
    "Riftmaker": "ap_only",
    "Horizon Focus": "ap_only",
    "Malignance": "ap_only",
    "Stormsurge": "ap_only",
    "Mejai's Soulstealer": "ap_only",
    # --- universal (resists / HP / tenacity / revive / cleanse) ---
    "Thornmail": "universal",
    "Guardian Angel": "universal",
    "Sterak's Gage": "universal",
    "Quicksilver Sash": "universal",
    "Mercury's Treads": "universal",
    "Plated Steelcaps": "universal",
    "Wit's End": "universal",
    "Jak'Sho, The Protean": "universal",
    "Spirit Visage": "universal",
    "Force of Nature": "universal",
    "Dead Man's Plate": "universal",
    "Randuin's Omen": "universal",
    "Frozen Heart": "universal",
    "Guinsoo's Rageblade": "universal",
    "Iceborn Gauntlet": "universal",
    "Kaenic Rookern": "universal",
    "Unending Despair": "universal",
    "Hollow Radiance": "universal",
}

OPEN_BUILD_EXCLUDED_DDRAGON_TAGS: frozenset[str] = frozenset({
    "Trinket", "Consumable", "Lane",
})

OPEN_BUILD_EXCLUDED_ITEM_IDS: frozenset[int] = frozenset({
    2003, 2031, 2033, 2010,
    3340, 3363, 3364,
    1101, 1102, 1103,
    3865,
})
