"""Read-only client for Riot's Live Client Data API (localhost, in-game only).

The endpoint listens on ``https://127.0.0.1:2999`` with a self-signed cert and
**no authentication**. We pin Riot's bundled CA (``riotgames.pem``) when present
so TLS is properly verified; only if that cert is missing do we fall back to
unverified transport (with a one-time warning). The client GETs ``allgamedata``
and never issues any write — the overlay is strictly observational.

When no game is running, port 2999 refuses the connection; every method here
swallows transport errors and returns ``None`` so callers can treat "no
response" as "no active game".
"""
from __future__ import annotations

import logging

import requests
import urllib3

from sylqon import config

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
log = logging.getLogger(__name__)


class LiveClient:
    """Thin GET-only wrapper over the Live Client Data API."""

    def __init__(self, base_url: str | None = None) -> None:
        self.base = (base_url or config.LIVE_CLIENT_URL).rstrip("/")
        self.session = requests.Session()
        self.session.verify = self._resolve_verify()

    @staticmethod
    def _resolve_verify():
        """Prefer Riot's pinned CA cert; fall back to no verification only if it
        is absent (the API would otherwise be unreachable on a fresh install)."""
        cert = config.LIVE_CLIENT_CERT
        try:
            if cert.exists():
                return str(cert)
        except OSError:
            pass
        log.warning(
            "Live Client CA cert not found at %s; falling back to unverified TLS "
            "for the localhost-only Live Client Data API. Drop Riot's riotgames.pem "
            "there to enable verification.", cert,
        )
        return False

    def _get(self, path: str) -> dict | list | None:
        try:
            resp = self.session.get(self.base + path, timeout=config.LIVE_CLIENT_TIMEOUT)
        except requests.RequestException:
            return None  # connection refused / timeout => no active game
        if resp.status_code != 200:
            return None
        try:
            return resp.json()
        except ValueError:
            return None

    def get_all_game_data(self) -> dict | None:
        """Full snapshot: gameData + activePlayer + allPlayers + events.
        Returns ``None`` when no game is running."""
        data = self._get("/liveclientdata/allgamedata")
        return data if isinstance(data, dict) else None

    def is_in_game(self) -> bool:
        return self.get_all_game_data() is not None
