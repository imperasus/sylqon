"""Sylqon hosted-service sync source — drop-in mirror of ``opgg_http``.

Exposes the same three calls the full sync uses (``fetch_all_meta``,
``fetch_detail``, ``fetch_synergies``) but serves them from ONE bulk request
to the hosted service's /api/meta-sync/full endpoint (our own Match-V5
aggregation). When ``SYLQON_META_URL`` is unset or the service is down,
``available()`` is False and the sync falls back to op.gg unchanged.
"""
from __future__ import annotations

import logging
import time

import requests

from sylqon import config

log = logging.getLogger(__name__)

# service role tokens -> local role strings (same vocabulary opgg_http emits)
_ROLE_TO_LOCAL = {"TOP": "top", "JUNGLE": "jungle", "MIDDLE": "middle",
                  "BOTTOM": "bottom", "UTILITY": "utility"}

_BUNDLE: dict | None = None
_BUNDLE_AT: float = 0.0
_BUNDLE_TTL = 600  # one sync run comfortably fits; refetch afterwards


def _bundle() -> dict | None:
    global _BUNDLE, _BUNDLE_AT
    base = config.SYLQON_META_URL.rstrip("/")
    if not base:
        return None
    if _BUNDLE is not None and time.time() - _BUNDLE_AT < _BUNDLE_TTL:
        return _BUNDLE
    try:
        r = requests.get(f"{base}/api/meta-sync/full", timeout=120)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict) or not data.get("entries"):
            log.warning("Sylqon meta-sync bundle is empty — falling back to op.gg")
            return None
        _BUNDLE, _BUNDLE_AT = data, time.time()
        log.info("Sylqon meta-sync bundle loaded: %d entries (patch %s)",
                 len(data["entries"]), data.get("patch"))
        return data
    except requests.RequestException as exc:
        log.warning("Sylqon meta-sync fetch failed: %s", exc)
        return None


def available() -> bool:
    return _bundle() is not None


def _entries_for(cid: int, role: str) -> dict | None:
    data = _bundle()
    if not data:
        return None
    for e in data["entries"]:
        if e["champion_id"] == cid and _ROLE_TO_LOCAL.get(e["role"]) == role:
            return e
    return None


def fetch_all_meta(region: str | None = None) -> dict[int, list[dict]]:
    """{champion_id: [{role, tier, win_rate, pick_rate}, ...]} — one bulk call."""
    data = _bundle()
    if not data:
        return {}
    out: dict[int, list[dict]] = {}
    for e in data["entries"]:
        role = _ROLE_TO_LOCAL.get(e["role"])
        if not role:
            continue
        out.setdefault(e["champion_id"], []).append({
            "role": role,
            "tier": e["tier"],
            "win_rate": e["win_rate"],
            "pick_rate": e["pick_rate"],
        })
    return out


def fetch_detail(cid: int, role: str,
                 region: str | None = None) -> tuple[dict | None, list[dict]]:
    """(build payload, counters) for one champion+role — served from the bundle."""
    e = _entries_for(cid, role)
    if e is None:
        return None, []
    payload = e.get("payload")
    if payload:
        payload = dict(payload)
        payload["role"] = role  # local role string for opgg_to_build
    counters = [{"champion_id": c["champion_id"], "opp_winrate": c["opp_winrate"]}
                for c in e.get("counters", [])]
    return payload, counters


def fetch_synergies(cid: int, role: str, region: str | None = None) -> list[dict]:
    e = _entries_for(cid, role)
    if e is None:
        return []
    return [{"synergy_champion_id": s["synergy_champion_id"], "win_rate": s["win_rate"]}
            for s in e.get("synergies", [])]
