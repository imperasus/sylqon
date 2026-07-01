"""Manual live check: Data Dragon catalog refresh + one real search->parse->
cache cycle. Needs network; not part of the offline test suite."""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from sylqon.cache.parser import BuildParser
from sylqon.cache.search import get_provider

from sylqon.cache.store import MetaCache
from sylqon.data.catalog import Catalog

cat = Catalog()
cat.refresh_if_stale()
print("patch:", cat.patch, "| items:", len(cat.items()))

provider = get_provider()
print("provider:", provider.name)
raw = provider.fetch_meta_text("Jinx", "bottom", cat.short_patch)
print("raw search text length:", len(raw))

build = BuildParser(cat).extract_build(raw, "bottom")
if build:
    MetaCache().put_build("Jinx", "bottom", build, provider.name, cat.patch)
    print("EXTRACTED:", [i["name"] for i in build["items"]])
    print("RUNES:", build["keystone"], "|", build["primary_runes"], "+",
          build["secondary_style"], build["secondary_runes"])
    print("SHARDS:", build["stat_shards"])
else:
    print("extraction returned None - seed fallback would be used for this champ")
