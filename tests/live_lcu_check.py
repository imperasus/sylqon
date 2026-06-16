"""Manual live check against the running League client.

Connects via lockfile/process credentials, injects the cached Jinx loadout's
item set and rune page TWICE, and verifies exactly one "Antigravity Meta"
entry of each exists afterwards (idempotent PUT overwrite). Spells are
skipped: there is no champ-select session outside a lobby.
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from sylqon import config, loadout as loadout_mod
from sylqon.cache.store import MetaCache
from sylqon.data.catalog import Catalog
from sylqon.lcu.client import LCUClient
from sylqon.lcu.injector import Injector
from sylqon.lcu.lobby import MatchContext

client = LCUClient.connect()
assert client, "Could not connect to the LCU"
summoner = client.current_summoner()
print("summoner:", summoner.get("displayName") or summoner.get("gameName"),
      "| id:", summoner["summonerId"])
print("gameflow phase:", client.gameflow_phase())

ctx = MatchContext(summoner_id=summoner["summonerId"], my_champion="Jinx",
                   my_champion_id=222, my_role="bottom", locked=True,
                   enemies=[], fingerprint="live-test")
build, source = MetaCache().get_build("Jinx", "bottom")
final = loadout_mod.from_candidate(build, ctx, source)
print("injecting build from:", source)

injector = Injector(client)
for attempt in (1, 2):
    ok_items = injector._inject_item_set(final, ctx.summoner_id, ctx.my_champion_id)
    ok_runes = injector._inject_rune_page(final)
    print(f"attempt {attempt}: item set ok={ok_items}, rune page ok={ok_runes}")

sets = client.get_json(f"/lol-item-sets/v1/item-sets/{ctx.summoner_id}/sets") or {}
titles = [s.get("title") for s in sets.get("itemSets", [])]
pages = client.get_json("/lol-perks/v1/pages") or []
page_names = [p.get("name") for p in pages]
ag_page = next(p for p in pages if p.get("name") == config.PROFILE_TITLE)

print("item set titles in client:", titles)
print("sylqon sets:", titles.count(config.PROFILE_TITLE))
print("sylqon rune pages:", page_names.count(config.PROFILE_TITLE))
print("rune page perk ids:", ag_page["selectedPerkIds"])
assert titles.count(config.PROFILE_TITLE) == 1, "item set not idempotent!"
assert page_names.count(config.PROFILE_TITLE) == 1, "rune page not idempotent!"
print("LIVE LCU CHECK PASSED")
