"""Regenerate tests/fixtures/catalog_snapshot.json from the local Data Dragon
catalog cache.

The snapshot pins the offline static-integrity suite (tests/test_static_integrity.py)
to a known-good catalog: champion display names and completed-item name→id
pairs. Re-run this after a patch bumps the catalog:

    python scripts/update_catalog_fixture.py

It refuses to run when the local catalog cache is missing — refresh it first by
starting the app once (python -m sylqon.server) with network access.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sylqon import config  # noqa: E402
from sylqon.data.catalog import Catalog  # noqa: E402


def main() -> int:
    src = config.CATALOG_CACHE_PATH
    if not src.exists():
        print(f"Catalog cache not found at {src}; run the app once to fetch it.")
        return 1
    # Load through Catalog so DDRAGON_ID_CORRECTIONS self-healing applies.
    data = Catalog()._data
    champ_data = data.get("champions", {})
    champions = sorted(info["name"] for info in champ_data.values())
    # attack/magic base scores per champion → the damage-type cross-check
    champion_info = {
        info["name"]: {"attack": info.get("attack", 0), "magic": info.get("magic", 0)}
        for info in sorted(champ_data.values(), key=lambda c: c["name"])
    }
    items = {name: it["id"] for name, it in sorted(data.get("items", {}).items())}
    if not champions or not items:
        print("Catalog cache is empty; refusing to write a hollow fixture.")
        return 1

    out = ROOT / "tests" / "fixtures" / "catalog_snapshot.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "patch": data.get("patch", "unknown"),
        "champions": champions,
        "champion_info": champion_info,
        "items": items,
    }, indent=1), encoding="utf-8")
    print(f"Wrote {out} (patch {data.get('patch')}, "
          f"{len(champions)} champions, {len(items)} items)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
