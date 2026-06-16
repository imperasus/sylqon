"""Direct op.gg HTTP fetchers for the automated full sync.

The same undocumented op.gg champion API that `cache/opgg_fetch.py` uses for
builds also exposes the lane-meta list, per-matchup counters and synergies:

  GET /api/{region}/champions/ranked                 -> all champions + positions + stats
  GET /api/{region}/champions/ranked/{cid}/{POS}     -> build (+ `counters`)
  GET /api/{region}/champions/ranked/{cid}/{POS}/synergies -> ally synergies

Counters are ``{champion_id, play, win}`` where ``win/play`` is the OPPONENT's
win rate vs this champion (high = it counters us). Every failure returns an empty
result so the sync can skip and continue.
"""
from __future__ import annotations

import logging

import requests

from sylqon import config
from sylqon.cache.opgg_fetch import _shape_payload

log = logging.getLogger(__name__)

_BASE = "https://lol-api-champion.op.gg/api/{region}/champions"
_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

# our role <-> op.gg position token
_ROLE_TO_POS = {"top": "TOP", "jungle": "JUNGLE", "middle": "MID",
                "bottom": "ADC", "utility": "SUPPORT"}
_POS_TO_ROLE = {"TOP": "top", "JUNGLE": "jungle", "MID": "middle",
                "MIDDLE": "middle", "ADC": "bottom", "BOTTOM": "bottom",
                "SUPPORT": "utility"}


def _get(url: str, timeout: int | None = None):
    try:
        resp = requests.get(url, headers=_HEADERS,
                            timeout=timeout or config.OPGG_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return (resp.json() or {}).get("data")
    except (requests.RequestException, ValueError) as exc:
        log.warning("op.gg GET failed %s: %s", url, exc)
        return None


def fetch_all_meta(region: str | None = None) -> dict[int, list[dict]]:
    """``{champion_id: [{role, tier, win_rate, pick_rate}, ...]}`` for every
    champion across every position it plays (one request)."""
    region = region or config.OPGG_REGION
    data = _get(_BASE.format(region=region) + "/ranked")
    out: dict[int, list[dict]] = {}
    for c in data or []:
        cid = c.get("id")
        positions = []
        for p in c.get("positions", []):
            role = _POS_TO_ROLE.get(p.get("name"))
            if not role:
                continue
            st = p.get("stats", {}) or {}
            td = st.get("tier_data", {}) or {}
            positions.append({
                "role": role,
                "tier": td.get("tier"),
                "win_rate": st.get("win_rate", 0.0),
                "pick_rate": st.get("pick_rate", 0.0),
            })
        if cid and positions:
            out[cid] = positions
    return out


def fetch_detail(cid: int, role: str, region: str | None = None) -> tuple[dict | None, list[dict]]:
    """``(opgg_build_payload | None, [{champion_id, opp_winrate}, ...])`` for a
    champion+role. The build payload is shaped for ``cache.opgg.opgg_to_build``."""
    pos = _ROLE_TO_POS.get(role)
    if not pos:
        return None, []
    data = _get(_BASE.format(region=region or config.OPGG_REGION) + f"/ranked/{cid}/{pos}")
    if not isinstance(data, dict):
        return None, []
    payload = _shape_payload(data, role)
    counters = []
    for c in data.get("counters") or []:
        play = c.get("play") or 0
        ocid = c.get("champion_id")
        if play > 0 and ocid:
            counters.append({"champion_id": ocid, "opp_winrate": c.get("win", 0) / play})
    return payload, counters


def fetch_synergies(cid: int, role: str, region: str | None = None) -> list[dict]:
    """``[{synergy_champion_id, win_rate}, ...]`` for a champion+role."""
    pos = _ROLE_TO_POS.get(role)
    if not pos:
        return []
    data = _get(_BASE.format(region=region or config.OPGG_REGION) + f"/ranked/{cid}/{pos}/synergies")
    out = []
    for s in data or []:
        scid = s.get("synergy_champion_id")
        if scid:
            out.append({"synergy_champion_id": scid, "win_rate": s.get("win_rate", 0.0)})
    return out
