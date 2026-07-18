"""Live OP.GG build fetch over op.gg's internal JSON API.

This is the autonomous counterpart to the Claude/MCP-driven `/api/opgg-build`
path: when the running pipeline hits a champion+role with no cached build, it
fetches the current ranked build straight from op.gg and converts it through the
same `opgg_to_build` pipeline, so the AI receives data in the usual shape.

The endpoint is undocumented and may change without notice — every failure mode
returns ``None`` so the caller falls back to the seed build.
"""
from __future__ import annotations

import logging
import time

import requests
from requests.adapters import HTTPAdapter

from sylqon import config

log = logging.getLogger(__name__)

_BASE = "https://lol-api-champion.op.gg/api/{region}/champions/ranked/{cid}/{pos}"

# Our internal role names -> op.gg position tokens.
_POSITION = {
    "top": "TOP",
    "jungle": "JUNGLE",
    "middle": "MID",
    "bottom": "ADC",
    "utility": "SUPPORT",
}

_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

# Shared connection pool — reused by the live fetch *and* the full sync
# (``mcp.opgg_http`` imports this module's helpers), so neither pays a fresh
# TLS handshake per request. Sized for the full sync's worker pool.
_SESSION = requests.Session()
_SESSION.mount("https://", HTTPAdapter(pool_connections=4, pool_maxsize=16))


def _request_json(url: str, *, timeout: int | None = None,
                  retries: int | None = None):
    """GET ``url`` and return parsed JSON, with a short exponential backoff on
    transient failures (timeout / connection drop / 5xx). 4xx and malformed JSON
    are not retried. Returns ``None`` once retries are exhausted, so every caller
    degrades gracefully to its seed/cache fallback."""
    timeout = timeout or config.OPGG_TIMEOUT_SECONDS
    retries = config.OPGG_RETRIES if retries is None else retries
    delay = 0.5
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = _SESSION.get(url, headers=_HEADERS, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_exc = exc
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            if not 500 <= status < 600:
                log.warning("op.gg GET %s failed (HTTP %s)", url, status)
                return None
            last_exc = exc
        except ValueError as exc:  # malformed JSON — a retry won't fix it
            log.warning("op.gg GET %s returned bad JSON: %s", url, exc)
            return None
        if attempt < retries:
            time.sleep(delay)
            delay *= 2
    log.warning("op.gg GET %s failed after %d attempt(s): %s",
                url, retries + 1, last_exc)
    return None


def fetch_opgg_payload(champion_id: int, role: str,
                       region: str | None = None) -> dict | None:
    """Fetch the top ranked build for a champion+role and shape it into the
    payload dict expected by ``cache.opgg.opgg_to_build``. Returns ``None`` on
    any network/parse failure or unknown role."""
    pos = _POSITION.get(role)
    if not pos:
        return None
    region = region or config.OPGG_REGION
    url = _BASE.format(region=region, cid=champion_id, pos=pos)
    raw = _request_json(url)
    data = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(data, dict):
        return None
    return _shape_payload(data, role)


def _top_ids(entries: list, key: str = "ids") -> list[int]:
    """First (most-picked) id group from an op.gg ranked-list section."""
    if entries and isinstance(entries[0], dict):
        return list(entries[0].get(key, []))
    return []


# How many distinct core combos to carry into the build payload. Enough for the
# matchup selector to have real alternatives, small enough to keep prompts lean.
CORE_OPTION_LIMIT = 4


def _core_options(entries: list, limit: int = CORE_OPTION_LIMIT) -> list[dict]:
    """Top core-item combos with their sample counts.

    op.gg lists purchase-order permutations of the same trio as separate rows
    (e.g. [A,B,C] and [A,C,B]); those are one build, so merge by item set —
    summing play/win and keeping the most-played permutation's ordering. The
    result is sorted by merged play count so the matchup selector's meta prior
    reads true popularity, not per-permutation slices."""
    merged: dict[frozenset, dict] = {}
    first_seen: dict[frozenset, int] = {}
    for idx, e in enumerate(entries):
        if not isinstance(e, dict):
            continue
        ids = [i for i in e.get("ids", []) if isinstance(i, int)]
        if len(ids) != 3:
            continue
        key = frozenset(ids)
        play = e.get("play") or 0
        win = e.get("win") or 0
        if key in merged:
            merged[key]["play"] += play
            merged[key]["win"] += win
        else:
            merged[key] = {"ids": ids, "play": play, "win": win}
            first_seen[key] = idx
    ranked = sorted(merged, key=lambda k: (-merged[k]["play"], first_seen[k]))
    return [merged[k] for k in ranked[:limit]]


def _shape_payload(data: dict, role: str) -> dict | None:
    core_options = _core_options(data.get("core_items", []))
    # Default core = the genuinely most-played combo (permutations merged);
    # fall back to the raw top row for payloads _core_options can't read.
    core = list(core_options[0]["ids"]) if core_options \
        else _top_ids(data.get("core_items", []))
    boots = _top_ids(data.get("boots", []))
    starters = _top_ids(data.get("starter_items", []))
    spells = _top_ids(data.get("summoner_spells", []))

    # Every summoner spell op.gg observes on this champion (across the top
    # combos). This is the ONLY set the AI may pick spells from — so it can
    # never suggest a spell nobody runs on the champion.
    spell_options: list[int] = []
    for combo in (data.get("summoner_spells") or [])[:4]:
        if isinstance(combo, dict):
            for sid in combo.get("ids", []):
                if sid not in spell_options:
                    spell_options.append(sid)

    runes_list = data.get("runes") or []
    runes = runes_list[0] if runes_list and isinstance(runes_list[0], dict) else {}

    # last_items is a flat, pick-rate-ranked list of single completed items; use
    # it as the situational pool (opgg_to_build dedupes against boots + core).
    drop = set(core) | set(boots)
    situational: list[int] = []
    for entry in data.get("last_items", []):
        for iid in (entry.get("ids", []) if isinstance(entry, dict) else []):
            if iid not in drop and iid not in situational:
                situational.append(iid)
    situational = situational[:6]

    if not core or not runes.get("primary_rune_ids"):
        log.warning("op.gg payload missing core/runes for role %s", role)
        return None

    return {
        "role": role,
        "starter_item_ids": starters,
        "boot_ids": boots,
        "core_item_ids": core,
        "core_options": core_options,
        # spread the situational pool across the three slot keys the converter
        # iterates; the split is cosmetic — they're unioned and deduped.
        "fourth_item_ids": situational[:2],
        "fifth_item_ids": situational[2:4],
        "sixth_item_ids": situational[4:6],
        "primary_page_id": runes.get("primary_page_id", 0),
        "primary_rune_ids": runes.get("primary_rune_ids", []),
        "secondary_page_id": runes.get("secondary_page_id", 0),
        "secondary_rune_ids": runes.get("secondary_rune_ids", []),
        "stat_mod_ids": runes.get("stat_mod_ids", []),
        "summoner_spell_ids": spells,
        "summoner_spell_options": spell_options,
    }
