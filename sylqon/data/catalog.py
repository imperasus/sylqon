"""Runtime catalog backed by Riot's public Data Dragon CDN.

Resolves the current patch, champion id -> name/threat-info mapping and the
item name -> id/description table the search parser and AI prompt use.
Cached on disk so the live match path never blocks on the network.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import requests

from sylqon import config

log = logging.getLogger(__name__)

DDRAGON_BASE = "https://ddragon.leagueoflegends.com"
CATALOG_TTL = 12 * 3600

# Items that should never appear in a completed build block.
EXCLUDED_ITEM_TAGS = {"Trinket", "Consumable"}

# Data Dragon publishes wrong item IDs for some items in certain patches.
# Map: wrong DDragon int ID → correct in-game int ID.
DDRAGON_ID_CORRECTIONS: dict[int, int] = {
    667666: 6676,  # The Collector — DDragon 16.x bug
}


class Catalog:
    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._load_disk()

    # -- loading -----------------------------------------------------------
    def _load_disk(self) -> None:
        try:
            self._data = json.loads(config.CATALOG_CACHE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._data = {}

    def _save_disk(self) -> None:
        tmp = config.CATALOG_CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data), encoding="utf-8")
        tmp.replace(config.CATALOG_CACHE_PATH)

    def _stale(self) -> bool:
        return (time.time() - self._data.get("fetched_at", 0)) > CATALOG_TTL

    def refresh_if_stale(self) -> None:
        """Network refresh — call from the background scheduler only."""
        if self._data and not self._stale():
            return
        try:
            versions = requests.get(f"{DDRAGON_BASE}/api/versions.json", timeout=15).json()
            patch = versions[0]
            champs = requests.get(
                f"{DDRAGON_BASE}/cdn/{patch}/data/en_US/champion.json", timeout=20
            ).json()["data"]
            items = requests.get(
                f"{DDRAGON_BASE}/cdn/{patch}/data/en_US/item.json", timeout=20
            ).json()["data"]
        except (requests.RequestException, KeyError, ValueError, IndexError) as exc:
            log.warning("Data Dragon refresh failed: %s", exc)
            return

        champions = {}
        for name_key, c in champs.items():
            champions[c["key"]] = {
                "name": c["name"],
                "id": name_key,
                "tags": c.get("tags", []),
                "attack": c.get("info", {}).get("attack", 0),
                "magic": c.get("info", {}).get("magic", 0),
            }

        item_table = {}
        for item_id, it in items.items():
            gold = it.get("gold", {})
            tags = set(it.get("tags", []))
            if not gold.get("purchasable", False) or tags & EXCLUDED_ITEM_TAGS:
                continue
            if not it.get("maps", {}).get("11", False):
                continue
            is_boots = "Boots" in tags
            raw_id = int(item_id)
            corrected_id = DDRAGON_ID_CORRECTIONS.get(raw_id, raw_id)
            if corrected_id != raw_id:
                log.debug("ID correction: %s %d → %d", it["name"], raw_id, corrected_id)
            item_table[it["name"]] = {
                "id": corrected_id,
                "gold": gold.get("total", 0),
                "plaintext": it.get("plaintext", ""),
                "tags": list(tags),
                "completed": (
                    (is_boots and gold.get("total", 0) >= 300)
                    or (gold.get("total", 0) >= 900 and not it.get("into"))
                ),
            }

        self._data = {
            "fetched_at": time.time(),
            "patch": patch,
            "champions": champions,
            "items": item_table,
        }
        self._save_disk()
        log.info("Catalog refreshed for patch %s (%d items, %d champions)",
                 patch, len(item_table), len(champions))

    # -- lookups (pure local reads) ------------------------------------------
    @property
    def patch(self) -> str:
        return self._data.get("patch", "current")

    @property
    def short_patch(self) -> str:
        parts = self.patch.split(".")
        return ".".join(parts[:2]) if len(parts) >= 2 else self.patch

    def champion_by_key(self, champion_id: int) -> dict | None:
        return self._data.get("champions", {}).get(str(champion_id))

    def champion_by_name(self, name: str) -> dict | None:
        for key, info in self._data.get("champions", {}).items():
            if info["name"].lower() == name.lower():
                return {**info, "key": key}
        return None

    def champion_by_slug(self, slug: str) -> dict | None:
        """Look up by Data Dragon id ("MissFortune"). The Live Client Data API
        sometimes reports the slug rather than the display name."""
        for key, info in self._data.get("champions", {}).items():
            if info.get("id", "").lower() == slug.lower():
                return {**info, "key": key}
        return None

    def champion_name(self, champion_id: int) -> str:
        info = self.champion_by_key(champion_id)
        return info["name"] if info else f"Champion#{champion_id}"

    def champion_slug(self, name: str) -> str:
        info = self.champion_by_name(name)
        return info["id"] if info else ""

    def all_champions(self) -> list[dict]:
        """Every champion as {name, slug, tags}, sorted by name — feeds the
        Dashboard's champion-pool editor."""
        out = [
            {"name": info["name"], "slug": info["id"], "tags": info.get("tags", [])}
            for info in self._data.get("champions", {}).values()
        ]
        return sorted(out, key=lambda c: c["name"])

    def items(self) -> dict[str, dict]:
        return self._data.get("items", {})

    def completed_items(self) -> dict[int, dict]:
        """Purchasable completed items, filtered for open-build use.

        Returns a dict keyed by integer item ID. Excludes excluded IDs,
        excluded DDragon tag categories, and items cheaper than 2200 gold.
        """
        from sylqon.data import static as _static
        result: dict[int, dict] = {}
        for name, it in self._data.get("items", {}).items():
            raw_id = it["id"]
            corrected_id = DDRAGON_ID_CORRECTIONS.get(raw_id, raw_id)
            if corrected_id in _static.OPEN_BUILD_EXCLUDED_ITEM_IDS:
                continue
            if set(it.get("tags", [])) & _static.OPEN_BUILD_EXCLUDED_DDRAGON_TAGS:
                continue
            if it.get("gold", 0) < 2200:
                continue
            result[corrected_id] = {**it, "name": name, "id": corrected_id}
        return result

    def items_for_threat(
        self,
        threat_tags: list[str],
        exclude_ids: set[int] | None = None,
        limit: int = 12,
    ) -> list[dict]:
        """Items from ITEM_COUNTER_TAGS whose tags overlap with threat_tags.

        Returns up to `limit` dicts sorted by overlap count descending.
        Each dict: {"id": int, "name": str, "description": str, "counter_tags": list[str]}.
        Items missing from the catalog's item table are silently skipped.
        """
        from sylqon.data import static as _static
        if exclude_ids is None:
            exclude_ids = set()
        threat_set = set(threat_tags)
        items_data = self._data.get("items", {})

        scored: list[tuple[int, dict]] = []
        for iid, tags in _static.ITEM_COUNTER_TAGS.items():
            if iid in exclude_ids:
                continue
            overlap = set(tags) & threat_set
            if not overlap:
                continue
            name = self.item_name(iid)
            if name is None:
                continue
            item = items_data.get(name)
            if item is None:
                continue
            scored.append((len(overlap), {
                "id": iid,
                "name": name,
                "description": item.get("plaintext", ""),
                "counter_tags": list(tags),
            }))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[:limit]]

    def boots_names(self) -> set[str]:
        return {n for n, it in self.items().items() if "Boots" in it.get("tags", [])}

    def item_id(self, name: str) -> int | None:
        it = self.items().get(name)
        return it["id"] if it else None

    def item_name(self, item_id: int) -> str | None:
        for name, it in self.items().items():
            if it["id"] == item_id:
                return name
        return None

    def item_description(self, name: str) -> str:
        it = self.items().get(name)
        return it.get("plaintext", "") if it else ""

    # -- LCU supplement -------------------------------------------------------
    def supplement_from_lcu(self, lcu_client) -> int:
        """Add items from the LCU game-data endpoint that are missing from the
        Data Dragon catalog (e.g. newly added or reworked items not yet in DDragon).

        Returns the number of new items added. Saves to disk if any were added.
        """
        # items.json is large (~1MB+); use a generous timeout for this one call.
        try:
            resp = lcu_client.get("/lol-game-data/assets/v1/items.json", timeout=30)
            lcu_items = resp.json() if resp.status_code == 200 else None
        except Exception as exc:
            log.warning("LCU items.json fetch failed: %s", exc)
            lcu_items = None
        if not isinstance(lcu_items, list):
            log.debug("LCU item endpoint returned unexpected type (%s); skipping supplement",
                      type(lcu_items).__name__)
            return 0

        existing_ids = {it["id"] for it in self._data.get("items", {}).values()}
        added = 0

        for it in lcu_items:
            item_id = it.get("id")
            name = (it.get("name") or "").strip()
            if not item_id or not name:
                continue
            if item_id in existing_ids:
                continue
            if not it.get("inStore", False):
                continue
            # LCU items.json has no "maps" field — all items in the endpoint
            # are SR-available by default; skip the map check entirely.
            categories = set(it.get("categories", []))
            if categories & {"Trinket", "Consumable"}:
                continue
            # Skip components (items that upgrade into something else)
            if it.get("to"):
                continue

            price_total = it.get("priceTotal", 0)
            is_boots = "Boots" in categories
            completed = (
                (is_boots and price_total >= 300)
                or (price_total >= 900 and not it.get("to"))
            )

            # Strip HTML tags from description to get plaintext
            raw_desc = it.get("description", "") or ""
            plaintext = re.sub(r"<[^>]+>", " ", raw_desc)
            plaintext = re.sub(r"\s+", " ", plaintext).strip()[:200]

            self._data.setdefault("items", {})[name] = {
                "id": item_id,
                "gold": price_total,
                "plaintext": plaintext,
                "tags": sorted(categories),
                "completed": completed,
            }
            existing_ids.add(item_id)
            added += 1
            log.debug("LCU supplement added item %s (id=%d)", name, item_id)

        if added > 0:
            self._save_disk()
            log.info("Supplemented catalog with %d item(s) from LCU", added)

        return added
