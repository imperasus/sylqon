"""Seed-derived, per-champion rune archetype pools.

Widens pool-constrained rune selection from the small hand-curated
``static.CHAMPION_RUNE_ARCHETYPES`` set to every champion that has an op.gg
seed build, by *deriving* the same pool shape straight from the bundled seed
data (``cache/seed.py`` BUILDS). The two sources are merged so the curated
ordering (meta-default keystone first) is preserved while seed data only ever
*adds* legal options.

Pool shape (identical to ``CHAMPION_RUNE_ARCHETYPES`` entries)::

    keystone_options          keystones op.gg runs (meta default first)
    primary_minor_flex        primary-tree minor runes the AI may pick from
    secondary_style_options   secondary trees op.gg actually uses
    secondary_minor_options   secondary-tree minor runes op.gg actually uses

Runtime breadth: the orchestrator calls :func:`register_build` with the live
op.gg *candidate* build for the champion being played, so its real keystone /
runes are always part of the pool (and the candidate page therefore always
passes ``_valid_rune_block``). Tests never register, so the pool is purely a
deterministic function of the bundled seed + static data — keeping the offline
suite hermetic.
"""
from __future__ import annotations

import logging

from sylqon.data import static

log = logging.getLogger(__name__)

_REQUIRED_KEYS = (
    "keystone_options",
    "primary_minor_flex",
    "secondary_style_options",
    "secondary_minor_options",
)

# Lazily-built merge of static archetypes + seed-derived pools (process cache).
_BASE_INDEX: dict[str, dict] | None = None
# Pools folded in at runtime from live candidate builds (champion -> pool).
_RUNTIME_INDEX: dict[str, dict] = {}


def _build_to_runeset(build: dict) -> dict | None:
    """Normalise a build dict to the four name-lists used by aggregation, or
    None if its rune block can't be resolved to known names."""
    keystone = build.get("keystone")
    if keystone not in static.KEYSTONES:
        return None
    primary = [r for r in (build.get("primary_runes") or []) if r in static.MINOR_RUNES]
    secondary_style = build.get("secondary_style")
    secondary = [r for r in (build.get("secondary_runes") or []) if r in static.MINOR_RUNES]
    if secondary_style not in static.RUNE_STYLES:
        return None
    return {
        "keystone": keystone,
        "primary_runes": primary,
        "secondary_style": secondary_style,
        "secondary_runes": secondary,
    }


def _aggregate(builds_by_champion: dict[str, list[dict]]) -> dict[str, dict]:
    """Fold every build for a champion into a single rune pool.

    Keystones are ordered by frequency (most-played first ≈ meta default); all
    other option lists are order-stable unions. Only self-consistent pools (a
    secondary tree that differs from the default keystone's tree, with at least
    one secondary minor) are emitted, so the result is always usable by
    ``_valid_rune_block``.
    """
    out: dict[str, dict] = {}
    for champ, builds in builds_by_champion.items():
        keystone_freq: dict[str, int] = {}
        primary: list[str] = []
        sec_styles: list[str] = []
        sec_minors: list[str] = []
        for raw in builds:
            rs = _build_to_runeset(raw)
            if rs is None:
                continue
            keystone_freq[rs["keystone"]] = keystone_freq.get(rs["keystone"], 0) + 1
            for r in rs["primary_runes"]:
                if r not in primary:
                    primary.append(r)
            if rs["secondary_style"] not in sec_styles:
                sec_styles.append(rs["secondary_style"])
            for r in rs["secondary_runes"]:
                if r not in sec_minors:
                    sec_minors.append(r)
        if not keystone_freq:
            continue
        # Sort by frequency desc, then first-seen order for determinism.
        keystones = sorted(keystone_freq, key=lambda k: (-keystone_freq[k], k))
        pool = {
            "keystone_options": keystones,
            "primary_minor_flex": primary,
            "secondary_style_options": sec_styles,
            "secondary_minor_options": sec_minors,
        }
        if _pool_valid(pool):
            out[champ] = pool
    return out


def _pool_valid(pool: dict) -> bool:
    """A pool is usable only if a secondary tree can legally pair with the
    default keystone (different tree) and there is at least one secondary minor
    to pick — otherwise ``_valid_rune_block`` could never accept any block."""
    if not pool.get("keystone_options"):
        return False
    default = pool["keystone_options"][0]
    primary_style = static.KEYSTONE_STYLE.get(default)
    if not any(s != primary_style for s in pool.get("secondary_style_options", [])):
        return False
    return bool(pool.get("secondary_minor_options"))


def _merge_pools(*pools: dict | None) -> dict:
    """Order-stable union of pools; the FIRST pool's ordering wins, so a curated
    archetype keeps its meta-default keystone at index 0."""
    merged: dict[str, list] = {k: [] for k in _REQUIRED_KEYS}
    for pool in pools:
        if not pool:
            continue
        for key in _REQUIRED_KEYS:
            for value in pool.get(key, []):
                if value not in merged[key]:
                    merged[key].append(value)
    return merged


def _builds_from_seed() -> dict[str, list[dict]]:
    """Champion -> [build-like dict] derived from the bundled op.gg seed table.

    Reads ``cache/seed.py`` BUILDS lazily (avoids importing the cache stack at
    module-import time) and maps the raw perk IDs to names via the static
    tables, so no catalog / network is required.
    """
    from sylqon.cache.seed import BUILDS  # local import: keep import graph light

    out: dict[str, list[dict]] = {}
    for row in BUILDS:
        champion = row[0]
        primary_rune_ids = row[8]
        secondary_page_id = row[9]
        secondary_rune_ids = row[10]
        if not primary_rune_ids:
            continue
        keystone = static.RUNE_BY_ID.get(primary_rune_ids[0])
        if not keystone:
            continue
        out.setdefault(champion, []).append({
            "keystone": keystone,
            "primary_runes": [static.RUNE_BY_ID.get(r) for r in primary_rune_ids[1:4]],
            "secondary_style": static.STYLE_BY_ID.get(secondary_page_id),
            "secondary_runes": [static.RUNE_BY_ID.get(r) for r in secondary_rune_ids[:2]],
        })
    return out


def _base_index() -> dict[str, dict]:
    """Merge of static archetypes and seed-derived pools, built once and cached."""
    global _BASE_INDEX
    if _BASE_INDEX is None:
        seed = _aggregate(_builds_from_seed())
        index: dict[str, dict] = {}
        for champ in set(seed) | set(static.CHAMPION_RUNE_ARCHETYPES):
            pool = _merge_pools(static.CHAMPION_RUNE_ARCHETYPES.get(champ), seed.get(champ))
            if _pool_valid(pool):
                index[champ] = pool
        _BASE_INDEX = index
    return _BASE_INDEX


def register_build(champion: str, build: dict) -> None:
    """Fold a champion-specific (op.gg/cache) build's rune page into the runtime
    pool so the live meta keystone/runes are always legal for that champion.

    No-op for unusable rune blocks. Called by the runtime per compile; never by
    the offline tests (so they stay deterministic on seed + static only).
    """
    if not isinstance(build, dict) or not champion:
        return
    pool = _aggregate({champion: [build]}).get(champion)
    if not pool:
        return
    existing = _RUNTIME_INDEX.get(champion)
    _RUNTIME_INDEX[champion] = _merge_pools(existing, pool) if existing else pool


def rune_pool_for_champion(champion: str) -> dict | None:
    """Return the seed-derived (+ static + any registered) rune pool for a
    champion, or None when nothing is known — in which case callers fall back to
    the global rune behaviour. Case-sensitive (champion display names)."""
    base = _base_index().get(champion)
    runtime = _RUNTIME_INDEX.get(champion)
    if base and runtime:
        return _merge_pools(base, runtime)
    return base or runtime
