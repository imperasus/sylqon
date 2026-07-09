"""Champion id → name/key resolver + Data Dragon asset URLs.

Backed by the bundled ``app/data/champions.json`` (generated from the repo's
``cache/ddragon_catalog.json`` — regenerate on patch bumps, same as
``advice/data/completed_items.json``). Kept self-contained so the service stays
independently containerizable (no import of the local ``sylqon`` package, no
runtime dependency on the repo-root ``cache/`` dir).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).resolve().parent / "data" / "champions.json"
_CDN = "https://ddragon.leagueoflegends.com/cdn"


@lru_cache(maxsize=1)
def _catalog() -> dict:
    with _DATA.open(encoding="utf-8") as fh:
        return json.load(fh)


def version() -> str:
    """Data Dragon patch the bundled catalog was generated from (e.g. '16.13.1')."""
    return _catalog().get("version", "")


def name_for(champion_id: int | str | None) -> str | None:
    """Display name for a numeric champion id, or None if unknown."""
    if champion_id is None:
        return None
    entry = _catalog()["champions"].get(str(champion_id))
    return entry["name"] if entry else None


def _key_for(champion_id: int | str | None) -> str | None:
    """Data Dragon key (image basename, e.g. 'MonkeyKing' for Wukong)."""
    if champion_id is None:
        return None
    entry = _catalog()["champions"].get(str(champion_id))
    return entry["key"] if entry else None


def square_url(champion_id: int | str | None) -> str | None:
    """Champion square icon URL on the Data Dragon CDN, version-pinned."""
    key = _key_for(champion_id)
    if not key:
        return None
    return f"{_CDN}/{version()}/img/champion/{key}.png"


def profile_icon_url(icon_id: int | None) -> str | None:
    """Summoner profile-icon URL on the Data Dragon CDN, version-pinned."""
    if icon_id is None:
        return None
    return f"{_CDN}/{version()}/img/profileicon/{icon_id}.png"
