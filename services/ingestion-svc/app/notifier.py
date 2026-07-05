"""Discord webhook delivery for post-game advice.

Webhook MVP of the roadmap's discord-gw: no bot token, no slash commands —
one channel gets the advice embed. Degrades gracefully: any failure returns
False and the watcher retries the match on its next cycle.
"""
from __future__ import annotations

import logging
import time

import requests

from app import config

log = logging.getLogger(__name__)

_GREEN = 0x57F287
_RED = 0xED4245

_LABELS = {
    "hu": {"win": "Győzelem", "loss": "Vereség", "lesson": "A meccs tanulsága"},
    "en": {"win": "Victory", "loss": "Defeat", "lesson": "Lesson of the match"},
}


def build_embed(advice: dict, participant, lang: str) -> dict:
    labels = _LABELS.get(lang, _LABELS["hu"])
    win = bool(participant.win)
    kda = f"{participant.kills}/{participant.deaths}/{participant.assists}"
    return {
        "username": "Sylqon Coach",
        "embeds": [
            {
                "title": f"{advice['champion']} · {labels['win'] if win else labels['loss']} · {kda}",
                "description": f"**{labels['lesson']}:**\n{advice['text']}",
                "color": _GREEN if win else _RED,
                "footer": {
                    "text": f"Sylqon · {advice['match_id']} · {advice['role'] or '?'}"
                },
            }
        ],
    }


class DiscordWebhookNotifier:
    def __init__(self, webhook_url: str | None = None, session=None, sleep=time.sleep):
        self.webhook_url = webhook_url if webhook_url is not None else config.DISCORD_WEBHOOK_URL
        self._session = session or requests.Session()
        self._sleep = sleep

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url)

    def send(self, advice: dict, participant, lang: str | None = None) -> bool:
        if not self.enabled:
            return False
        return self.send_payload(build_embed(advice, participant, lang or config.WATCH_LANG))

    def send_payload(self, payload: dict) -> bool:
        if not self.enabled:
            return False
        for attempt in range(2):
            try:
                r = self._session.post(self.webhook_url, json=payload, timeout=10)
                if r.status_code == 429:
                    retry_after = float(r.headers.get("Retry-After", 2))
                    log.warning("Discord webhook rate-limited, waiting %.1fs", retry_after)
                    self._sleep(retry_after)
                    continue
                if 200 <= r.status_code < 300:
                    return True
                log.warning("Discord webhook returned %s: %s", r.status_code, r.text[:200])
                return False
            except requests.RequestException as exc:
                log.warning("Discord webhook failed (attempt %d): %s", attempt + 1, exc)
        return False
