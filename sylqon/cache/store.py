"""Local meta cache: zero-latency reads during a live match, with the
hardcoded seed file as final fallback.

Layout of meta_cache.json:
{
  "patch": "14.x.y",
  "tracked": {"Ahri|middle": <last_played_ts>, ...},
  "builds": {
    "Ahri|middle": {
      "updated_at": ts,
      "source": "opgg",
      "build": {...},
      "raw_payload": {...}   # OP.GG payload stored for re-conversion after catalog updates
    }
  }
}
"""
from __future__ import annotations

import json
import logging
import threading
import time

from sylqon import config

log = logging.getLogger(__name__)


def build_key(champion: str, role: str) -> str:
    return f"{champion}|{role}"


class MetaCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data = self._load(config.META_CACHE_PATH) or {
            "patch": "", "tracked": {}, "builds": {}, "pool": {},
        }
        self._data.setdefault("pool", {})
        self._seed = self._load(config.SEED_BUILDS_PATH) or {
            "role_defaults": {}, "champions": {},
        }

    @staticmethod
    def _load(path) -> dict | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _save(self) -> None:
        tmp = config.META_CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        tmp.replace(config.META_CACHE_PATH)

    # -- read path (live match, must never touch the network) ----------------
    def get_build(self, champion: str, role: str) -> tuple[dict, str]:
        """Returns (build, source). Order: fresh cache -> stale cache ->
        champion seed -> role-default seed."""
        key = build_key(champion, role)
        with self._lock:
            entry = self._data["builds"].get(key)
        if entry and entry.get("build"):
            age = time.time() - entry.get("updated_at", 0)
            source = "cache" if age <= config.CACHE_TTL_SECONDS else "cache-stale"
            return entry["build"], source

        seeded = self._seed.get("champions", {}).get(key)
        if seeded:
            return seeded, "seed"

        default = self._seed.get("role_defaults", {}).get(role)
        if default:
            return default, "seed-role-default"

        # Absolute last resort: any role default.
        any_default = next(iter(self._seed.get("role_defaults", {}).values()), {})
        return any_default, "seed-any"

    # -- write path (background scheduler) -----------------------------------
    def put_build(self, champion: str, role: str, build: dict, source: str,
                  patch: str, raw_payload: dict | None = None) -> None:
        with self._lock:
            key = build_key(champion, role)
            entry: dict = {
                "updated_at": time.time(),
                "source": source,
                "build": build,
            }
            if raw_payload is not None:
                entry["raw_payload"] = raw_payload
            elif existing := self._data["builds"].get(key):
                # Preserve existing raw_payload so re-conversion remains possible
                if rp := existing.get("raw_payload"):
                    entry["raw_payload"] = rp
            self._data["patch"] = patch
            self._data["builds"][key] = entry
            self._save()
        log.info("Cached build for %s %s (source=%s)", champion, role, source)

    # -- post-supplement re-conversion ---------------------------------------
    def reconvert_opgg_builds(self, catalog) -> int:
        """Re-convert all OP.GG-sourced builds that have a stored raw_payload.

        Called after the LCU catalog supplement adds previously missing items.
        Returns the number of builds that were updated.
        """
        from sylqon.cache.opgg import opgg_to_build

        # Snapshot entries without holding the lock during conversion
        with self._lock:
            entries = {k: dict(v) for k, v in self._data["builds"].items()}

        reconverted = 0
        for key, entry in entries.items():
            if entry.get("source") != "opgg":
                continue
            payload = entry.get("raw_payload")
            if not payload:
                continue
            new_build = opgg_to_build(payload, catalog)
            if new_build is None:
                continue
            old_items = entry.get("build", {}).get("items", [])
            new_items = new_build.get("items", [])
            # Update if items list changed (new item resolved from LCU supplement)
            if [i["id"] for i in new_items] != [i["id"] for i in old_items]:
                champ, _, role = key.partition("|")
                self.put_build(champ, role, new_build, "opgg", catalog.patch, payload)
                log.info("Re-converted %s %s: %d → %d items after catalog supplement",
                         champ, role, len(old_items), len(new_items))
                reconverted += 1

        return reconverted

    def buildable_for_role(self, role: str) -> list[str]:
        """Every champion we can build a loadout for in a role (cached builds
        first, then bundled seed champions). De-duplicated, order-stable."""
        names: list[str] = []
        seen: set[str] = set()

        def add(champ: str) -> None:
            if champ and champ not in seen:
                seen.add(champ)
                names.append(champ)

        with self._lock:
            cached_keys = list(self._data["builds"].keys())
            seed_keys = list(self._seed.get("champions", {}).keys())
        for key in cached_keys + seed_keys:
            champ, _, key_role = key.partition("|")
            if key_role == role:
                add(champ)
        return names

    def champions_for_role(self, role: str) -> list[str]:
        """The player's 'prioritised' champion pool for a role used by the
        recommender: the hand-curated pool if the user set one, otherwise every
        buildable champion for the role."""
        with self._lock:
            user_pool = list(self._data.get("pool", {}).get(role, []))
        if user_pool:
            return user_pool
        return self.buildable_for_role(role)

    # -- champion pool (user-curated, edited from the Dashboard) --------------
    def get_pool(self) -> dict[str, list[str]]:
        with self._lock:
            return {role: list(champs)
                    for role, champs in self._data.get("pool", {}).items()}

    def set_pool(self, pool: dict[str, list[str]]) -> dict[str, list[str]]:
        """Replace the curated champion pool. Keeps only the five known roles
        and string champion names; persists immediately."""
        cleaned: dict[str, list[str]] = {}
        for role in ("top", "jungle", "middle", "bottom", "utility"):
            champs = pool.get(role, [])
            if isinstance(champs, list):
                seen: set[str] = set()
                ordered = []
                for c in champs:
                    if isinstance(c, str) and c.strip() and c not in seen:
                        seen.add(c)
                        ordered.append(c.strip())
                cleaned[role] = ordered
        with self._lock:
            self._data["pool"] = cleaned
            self._save()
        log.info("Champion pool updated: %s",
                 {r: len(c) for r, c in cleaned.items() if c})
        return cleaned

    def track_champion(self, champion: str, role: str) -> None:
        """Remember champions the user actually plays so the scheduler
        prioritises them on refresh cycles."""
        with self._lock:
            self._data["tracked"][build_key(champion, role)] = time.time()
            self._save()

    def stats(self) -> dict:
        with self._lock:
            updated = [e.get("updated_at", 0) for e in self._data["builds"].values()]
            return {
                "builds": len(self._data["builds"]),
                "tracked": len(self._data["tracked"]),
                "last_sync": max(updated) if updated else None,
            }

    def refresh_targets(self, current_patch: str) -> list[tuple[str, str]]:
        """Keys needing a re-search: tracked or seeded champions whose cache
        entry is missing, stale, or from an older patch."""
        now = time.time()
        with self._lock:
            keys = set(self._data["tracked"]) | set(self._seed.get("champions", {}))
            patch_changed = self._data.get("patch") != current_patch
            out = []
            for key in sorted(keys):
                entry = self._data["builds"].get(key)
                fresh = (
                    entry
                    and not patch_changed
                    and (now - entry.get("updated_at", 0)) <= config.CACHE_TTL_SECONDS
                )
                if not fresh:
                    champ, _, role = key.partition("|")
                    out.append((champ, role))
            return out
