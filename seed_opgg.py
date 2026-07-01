"""One-shot seeder: pushes OP.GG MCP data directly into MetaCache.

For normal use, the runtime auto-seeds on first launch. Run this script
manually after updating the BUILDS table in sylqon/cache/seed.py to
force a full re-seed without restarting the application.
"""
import logging

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

from sylqon.cache.seed import BUILDS, seed_cache
from sylqon.cache.store import MetaCache
from sylqon.data.catalog import Catalog

catalog = Catalog()
catalog.refresh_if_stale()
store = MetaCache()

ok = seed_cache(store, catalog)

# Print summary
for row in BUILDS:
    champion, role = row[0], row[1]
    build, _ = store.get_build(champion, role)
    items = [it["name"] for it in build.get("items", [])]
    pool = [it["name"] for it in build.get("situational_pool", [])]
    ks = build.get("keystone", "?")
    print(f"{'OK':<4} {champion:<14} {role:<8} | {ks:<22} | {items}")
    print(f"     pool({len(pool)}): {pool}")

print(f"\n{ok} cached, {len(BUILDS) - ok} failed")
