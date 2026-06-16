"""Manual live check: full loadout compilation through local Ollama.

Builds a synthetic CC/burst-heavy enemy team, feeds the cached/seed Jinx
build through the prompt compiler and Ollama, validates the result, and
prints the exact rune payload the injector would PUT. Runs the evaluation
twice to demonstrate determinism. Needs a running Ollama; no League client.
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from sylqon import loadout as loadout_mod
from sylqon.ai.engine import OllamaEngine
from sylqon.ai.prompts import compile_prompt
from sylqon.cache.store import MetaCache
from sylqon.data.catalog import Catalog
from sylqon.lcu.injector import merge_stat_shards
from sylqon.lcu.lobby import EnemyProfile, MatchContext

catalog = Catalog()
store = MetaCache()
engine = OllamaEngine()
assert engine.available(), "Ollama is not running"

enemies = [
    EnemyProfile("Malzahar", 90, "middle", "AP", ["Mage"], ["heavy_cc", "suppression"]),
    EnemyProfile("Leona", 89, "utility", "Mixed", ["Tank", "Support"], ["heavy_cc"]),
    EnemyProfile("Zed", 238, "jungle", "AD", ["Assassin"], ["burst_ad"]),
    EnemyProfile("Soraka", 16, "bottom", "AP", ["Support"], ["heavy_healing"]),
    EnemyProfile("Malphite", 54, "top", "Mixed", ["Tank"], ["heavy_cc", "tank"]),
]
ctx = MatchContext(summoner_id=1, my_champion="Jinx", my_champion_id=222,
                   my_role="bottom", locked=True, enemies=enemies, fingerprint="t")

candidate, source = store.get_build("Jinx", "bottom")
print("candidate source:", source)
prompt = compile_prompt(ctx, candidate, catalog)
base = loadout_mod.from_candidate(candidate, ctx, source)

results = []
for run in (1, 2):
    ai = engine.evaluate(prompt)
    final = loadout_mod.apply_ai_decision(base, ai, ctx, catalog)
    payload = merge_stat_shards(final.rune_perk_ids, final.shard_ids)
    results.append((tuple(i["name"] for i in final.items),
                    (final.spell1, final.spell2), tuple(payload)))
    print(f"--- run {run} ---")
    print("ITEMS :", [i["name"] for i in final.items])
    print("SPELLS:", f"D={final.spell1}  F={final.spell2}")
    print("PERKS :", payload, "<- shards on tail:", payload[-3:])
    print("WHY   :", final.reasoning)

print("DETERMINISTIC ACROSS RUNS:", results[0] == results[1])
