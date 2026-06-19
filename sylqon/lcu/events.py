"""LCU WebSocket event subscription.

The League client exposes a WAMP-style WebSocket on the same port and
credentials as the REST API. Subscribing to an event topic lets us react the
instant something changes — a champ-select hover, a lobby member joining, a
timer tick — instead of polling the matching REST resource on a fixed cadence.

Wire protocol (the subset we use):
  * connect to wss://127.0.0.1:{port}/ with Basic auth (riot:token), self-signed
  * subscribe:   send [5, "<topic>"]            (5 = SUBSCRIBE)
  * unsubscribe: send [6, "<topic>"]            (6 = UNSUBSCRIBE)
  * event in:    [8, "<topic>", {data, eventType, uri}]   (8 = EVENT)

``LcuEventBus`` multiplexes many topics over a single connection: register a
callback per topic, and the bus subscribes to all of them, routes each push to
the matching callbacks, and re-subscribes to everything after a reconnect. It
runs on its own daemon thread; callbacks run on that thread, so a slow callback
throttles event consumption for *all* topics — keep them cheap (the runtime
debounces heavy work via state diffing and off-thread workers).

``ChampSelectListener`` is a thin back-compat wrapper around the bus bound to
the champ-select session topic.
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
LOBBY_TOPIC = "OnJsonApiEvent_lol-lobby_v1_lobby"
EOG_TOPIC = "OnJsonApiEvent_lol-end-of-game_v1_eog-stats-block"
# Gameflow phase pushes a bare phase string as the event ``data`` (e.g.
# "ChampSelect", "InProgress", "EndOfGame") rather than a resource dict.
GAMEFLOW_TOPIC = "OnJsonApiEvent_lol-gameflow_v1_gameflow-phase"

_SUBSCRIBE = 5
_EVENT = 8

# Callback receives (data, event_type): ``data`` is the raw resource dict (or
# ``None`` on a Delete), ``event_type`` is "Create" / "Update" / "Delete".
EventCallback = Callable[[dict | None, str], None]


class LcuEventBus:
    """Multiplexes several LCU event topics over one WebSocket connection.

    Register callbacks with ``subscribe(topic, callback)`` before or after
    ``start()``. The bus connects once, subscribes to every registered topic,
    dispatches each incoming event to the callbacks for its topic, and
    auto-reconnects (re-subscribing to all topics) while running.
    """

    def __init__(self, creds: LCUCredentials) -> None:
        self._creds = creds
        self._callbacks: dict[str, list[EventCallback]] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ws: websocket.WebSocket | None = None

    # --------------------------------------------------------- subscriptions
    def subscribe(self, topic: str, callback: EventCallback) -> None:
        """Register ``callback`` for ``topic``. If the bus is already connected,
        the topic is subscribed immediately; otherwise it is picked up the next
        time the run thread (re)connects."""
        with self._lock:
            new_topic = topic not in self._callbacks
            self._callbacks.setdefault(topic, []).append(callback)
            ws = self._ws
        if new_topic and ws is not None:
            try:
                ws.send(json.dumps([_SUBSCRIBE, topic]))
                log.debug("Subscribed to %s (live)", topic)
            except Exception:
                # A send failure just means we're mid-reconnect; the run loop
                # will resubscribe everything on the next connect.
                log.debug("Live subscribe to %s failed", topic, exc_info=True)

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="lcu-event-bus", daemon=True)
        self._thread.start()
        log.info("LCU event bus started (%d topic(s))", len(self._callbacks))

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
                self._resubscribe_all()
                self._consume()
            except Exception as exc:
                if not self._stop.is_set():
                    log.debug("LCU event bus connection dropped: %s", exc)
            finally:
                self._close_socket()
            # Brief backoff before reconnecting (champ select may have ended,
            # or the client may be momentarily unavailable).
            if not self._stop.is_set():
                self._stop.wait(1.0)

    def _resubscribe_all(self) -> None:
        assert self._ws is not None
        with self._lock:
            topics = list(self._callbacks)
        for topic in topics:
            self._ws.send(json.dumps([_SUBSCRIBE, topic]))
            log.debug("Subscribed to %s", topic)

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
        topic = msg[1]
        payload = msg[2]
        if not isinstance(payload, dict):
            return
        with self._lock:
            callbacks = list(self._callbacks.get(topic, ()))
        data = payload.get("data")
        event_type = payload.get("eventType", "Update")
        for cb in callbacks:
            try:
                cb(data, event_type)
            except Exception:
                log.exception("LCU event handler for %s failed", topic)

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


class ChampSelectListener:
    """Back-compat wrapper: an event bus bound to the champ-select session topic.

    ``on_event(data, event_type)`` is invoked for every champ-select push, with
    the same semantics as before the multiplexer refactor.
    """

    def __init__(self, creds: LCUCredentials,
                 on_event: EventCallback) -> None:
        self._bus = LcuEventBus(creds)
        self._bus.subscribe(CHAMP_SELECT_TOPIC, on_event)

    def start(self) -> None:
        self._bus.start()
        log.info("Champ-select WebSocket listener started")

    def stop(self) -> None:
        self._bus.stop()

    def is_running(self) -> bool:
        return self._bus.is_running()
