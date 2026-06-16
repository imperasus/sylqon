"""Built-in OP.GG seed data and auto-seeder for fresh installations.

`seed_cache(store, catalog)` is called automatically by the runtime when
meta_cache.json has no builds. It produces the same output as running
seed_opgg.py manually but without requiring a separate script invocation.

seed_opgg.py now simply imports and calls this module so there is a single
source of truth for the BUILDS table.
"""
from __future__ import annotations

import logging

from sylqon.cache.opgg import opgg_to_build
from sylqon.cache.store import MetaCache
from sylqon.data.catalog import Catalog

log = logging.getLogger(__name__)

# Columns:
#   champion, role,
#   boot_ids, core_item_ids,
#   fourth_item_ids, fifth_item_ids, sixth_item_ids,
#   primary_page_id, primary_rune_ids,
#   secondary_page_id, secondary_rune_ids,
#   stat_mod_ids, starter_item_ids, summoner_spell_ids
BUILDS: list[tuple] = [
    ("Hwei",         "bottom",
     [3020], [2503, 6653, 4645],
     [3089, 3157, 3135], [3089, 3157, 3135], [3157, 3102, 3089],
     8200, [8992, 8226, 8210, 8237], 8000, [8017, 9105],
     [5005, 5008, 5001], [1056, 2003, 2003], [4, 12]),

    ("Hwei",         "middle",
     [3020], [2503, 6653, 4645],
     [3089, 3157, 3135], [3089, 3157, 3135], [4629, 3157, 3089],
     8200, [8992, 8226, 8210, 8237], 8000, [8017, 9105],
     [5005, 5008, 5001], [1056, 2003, 2003], [4, 12]),

    ("Hwei",         "utility",
     [3020], [2503, 6653, 4645],
     [3165, 3157, 3089], [3089, 3157, 3135], [3089, 6653],
     8200, [8992, 8226, 8210, 8237], 8000, [8009, 9105],
     [5008, 5008, 5001], [2003, 2003], [4, 7]),

    ("Brand",        "bottom",
     [3020], [2503, 3116, 6653],
     [4645, 3157, 8010], [3157, 3089, 4645], [3089, 3165, 3157],
     8200, [8992, 8226, 8210, 8237], 8000, [8009, 9105],
     [5008, 5008, 5001], [1056, 2003, 2003], [4, 12]),

    ("Brand",        "middle",
     [3020], [2503, 3116, 6653],
     [3157, 4645, 3089], [3165, 3089, 3157], [3135, 3165, 8010],
     8200, [8992, 8226, 8210, 8237], 8000, [8009, 8014],
     [5007, 5008, 5001], [1056, 2003, 2003], [4, 12]),

    ("Brand",        "utility",
     [3020], [3116, 6653, 3165],
     [3157, 3165, 3089], [3157, 3089, 3135], [3100],
     8200, [8992, 8226, 8210, 8237], 8000, [8009, 8017],
     [5008, 5008, 5001], [2003, 2003], [4, 14]),

    ("Smolder",      "bottom",
     [3008], [3508, 3071, 3161],
     [3094, 3031, 2517], [3026, 3031, 3094], [3026, 2517, 3031],
     8200, [8992, 8275, 8234, 8236], 8300, [8304, 8316],
     [5008, 5010, 5001], [1055, 2003], [4, 21]),

    ("Jinx",         "bottom",
     [3006], [2523, 3046, 3031],
     [3036, 3033, 3031], [3026, 3072, 3139], [3026, 3072, 3139],
     8000, [8008, 8009, 9103, 8017], 8300, [8313, 8321],
     [5005, 5008, 5011], [1086, 2003, 2003], [4, 21]),

    ("Miss Fortune", "bottom",
     [3009], [6697, 6676, 3031],
     [3036, 3033, 3031], [3072, 3094, 3026], [3026, 3072, 3094],
     8300, [8369, 8321, 8345, 8316], 8200, [8226, 8236],
     [5008, 5008, 5011], [1055, 2003], [4, 21]),

    ("Kog'Maw",      "bottom",
     [3006], [3153, 3124, 3085],
     [3302, 6665, 3085], [6665, 3091, 3302], [6665, 3091, 3026],
     8000, [8008, 9111, 9103, 8299], 8400, [8429, 8451],
     [5005, 5008, 5001], [1086, 2003, 2003], [4, 21]),

    ("Nocturne",     "jungle",
     [3047], [3073, 6631, 3071],
     [3026, 6333, 3036], [3026, 6333, 3156], [3026, 6333, 6695],
     8000, [8010, 9111, 9104, 8299], 8100, [8106, 8140],
     [5005, 5008, 5001], [1101, 2003], [4, 11]),
]


def seed_cache(store: MetaCache, catalog: Catalog) -> int:
    """Convert all built-in BUILDS entries and store them in the MetaCache.

    Returns the number of builds successfully stored.
    Skips entries where opgg_to_build resolves fewer than 4 items (unresolvable
    due to a catalog gap — e.g. new patch items not yet in Data Dragon).
    """
    patch = catalog.patch
    ok = 0
    for row in BUILDS:
        (champion, role, boot_ids, core_ids, fourth_ids, fifth_ids, sixth_ids,
         pp_id, pr_ids, sp_id, sr_ids, sm_ids, starter_ids, spell_ids) = row
        payload = {
            "champion": champion, "role": role,
            "boot_ids": boot_ids, "core_item_ids": core_ids,
            "fourth_item_ids": fourth_ids, "fifth_item_ids": fifth_ids,
            "sixth_item_ids": sixth_ids,
            "primary_page_id": pp_id, "primary_rune_ids": pr_ids,
            "secondary_page_id": sp_id, "secondary_rune_ids": sr_ids,
            "stat_mod_ids": sm_ids, "starter_item_ids": starter_ids,
            "summoner_spell_ids": spell_ids,
        }
        build = opgg_to_build(payload, catalog)
        if build:
            store.put_build(champion, role, build, "opgg", patch, raw_payload=payload)
            log.info("Seeded %s %s (%d items, pool %d)",
                     champion, role, len(build["items"]),
                     len(build.get("situational_pool", [])))
            ok += 1
        else:
            log.warning("Seed failed for %s %s (catalog gaps?)", champion, role)
    return ok
