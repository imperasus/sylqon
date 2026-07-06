"""Fetch a meta build from the hosted Sylqon service (own Match-V5 aggregation).

The op.gg replacement path: the service's /api/meta-build endpoint returns the
exact payload shape ``_shape_payload`` produces, so the standard
``opgg_to_build`` conversion + static-table validation pipeline is reused
unchanged. Disabled unless ``SYLQON_META_URL`` is set — the local product's
behaviour is untouched by default. Any failure returns None and the caller
falls back to op.gg."""
from __future__ import annotations

import logging
from urllib.parse import quote

import requests

from sylqon import config

log = logging.getLogger(__name__)


def fetch_sylqon_payload(champion: str, role: str) -> dict | None:
    base = config.SYLQON_META_URL.rstrip("/")
    if not base:
        return None
    try:
        r = requests.get(
            f"{base}/api/meta-build/{quote(champion, safe='')}",
            params={"role": role},
            timeout=config.SYLQON_META_TIMEOUT,
        )
        if r.status_code == 404:
            log.info("Sylqon service has no build for %s %s yet", champion, role)
            return None
        r.raise_for_status()
        payload = r.json()
        if not isinstance(payload, dict) or not payload.get("core_item_ids"):
            log.warning("Sylqon service payload for %s %s is unusable", champion, role)
            return None
        payload["role"] = role  # keep the local role string for opgg_to_build
        return payload
    except requests.RequestException as exc:
        log.warning("Sylqon service fetch failed for %s %s: %s", champion, role, exc)
        return None
