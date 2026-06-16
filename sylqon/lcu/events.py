"""LCU WebSocket event subscription.

The League client exposes a WAMP-style WebSocket on the same port and
credentials as the REST API. Subscribing to an event topic lets us react the
instant champ select changes — a hover, a ban, a lock-in, a timer tick —
instead of polling `/lol-champ-select/v1/session` on a fixed cadence.

Wire protocol (the subset we use):
  * connect to wss://127.0.0.1:{port}/ with Basic auth (riot:token), self-signed
  * subscribe:   send [5, "<topic>"]            (5 = SUBSCRIBE)
  * unsubscribe: send [6, "<topic>"]            (6 = UNSUBSCRIBE)
  * event in:    [8, "<topic>", {data, eventType, uri}]   (8 = EVENT)

We expose one listener bound to the champ-select session topic. It runs on its
own daemon thread, auto-reconnects while running, and hands every event payload
to a callback. State diffing (deciding which events are worth acting on) is the
caller's job — see runtime.PipelineRunner.
"""
from __future__ import annotations

import json
import logging
import ssl
import threading
from typing import Callable

import websocket

from sylqon.lcu.client import LCUCredentials

log = logging.getLogger(__name__)

CHAMP_SELECT_TOPIC = "OnJsonApiEvent_lol-champ-select_v1_session"

_SUBSCRIBE = 5
_EVENT = 8


class ChampSelectListener:
    """Subscribes to the champ-select session topic over the LCU WebSocket and
    invokes ``on_event(data, event_type)`` for every push.

    ``data`` is the raw session dict (or ``None`` on a Delete). ``event_type``
    is one of "Create" / "Update" / "Delete". The callback runs on the listener
    thread, so a slow callback throttles event consumption — which is fine here
    because the runtime debounces heavy work via state diffing.
    """

    def __init__(self, creds: LCUCredentials,
                 on_event: Callable[[dict | None, str], None]) -> None:
        self._creds = creds
        self._on_event = on_event
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ws: websocket.WebSocket | None = None

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="lcu-champ-select-ws", daemon=True)
        self._thread.start()
        log.info("Champ-select WebSocket listener started")

    def stop(self) -> None:
        self._stop.set()
        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        self._thread = None

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ---------------------------------------------------------------- thread
    def _run(self) -> None:
        url = f"wss://127.0.0.1:{self._creds.port}/"
        header = [f"Authorization: Basic {self._basic_auth()}"]
        while not self._stop.is_set():
            try:
                self._ws = websocket.create_connection(
                    url, header=header,
                    sslopt={"cert_reqs": ssl.CERT_NONE},
                    timeout=5,
                )
                self._ws.send(json.dumps([_SUBSCRIBE, CHAMP_SELECT_TOPIC]))
                log.debug("Subscribed to %s", CHAMP_SELECT_TOPIC)
                self._consume()
            except Exception as exc:
                if not self._stop.is_set():
                    log.debug("Champ-select WS connection dropped: %s", exc)
            finally:
                self._close_socket()
            # Brief backoff before reconnecting (champ select may have ended,
            # or the client may be momentarily unavailable).
            if not self._stop.is_set():
                self._stop.wait(1.0)

    def _consume(self) -> None:
        assert self._ws is not None
        # recv() blocks; a short socket timeout lets us notice _stop promptly.
        self._ws.settimeout(1.0)
        while not self._stop.is_set():
            try:
                raw = self._ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            if not raw:
                continue
            self._dispatch(raw)

    def _dispatch(self, raw: str | bytes) -> None:
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            return
        if not (isinstance(msg, list) and len(msg) == 3 and msg[0] == _EVENT):
            return
        payload = msg[2]
        if not isinstance(payload, dict):
            return
        try:
            self._on_event(payload.get("data"), payload.get("eventType", "Update"))
        except Exception:
            log.exception("Champ-select event handler failed")

    # ----------------------------------------------------------------- utils
    def _basic_auth(self) -> str:
        import base64
        token = f"riot:{self._creds.token}".encode()
        return base64.b64encode(token).decode()

    def _close_socket(self) -> None:
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
