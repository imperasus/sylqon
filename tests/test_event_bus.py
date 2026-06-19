"""Offline tests for the multiplexed LCU event bus.

Exercise topic routing, live + reconnect (re)subscription, and callback
isolation against a fake WebSocket — no real socket or League client.

Run: python -m pytest tests/test_event_bus.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sylqon.lcu.client import LCUCredentials
from sylqon.lcu.events import (
    CHAMP_SELECT_TOPIC, LOBBY_TOPIC, ChampSelectListener, LcuEventBus,
)

CREDS = LCUCredentials(port=12345, token="tok")
_SUBSCRIBE, _EVENT = 5, 8


class FakeWS:
    """Records frames sent over the socket."""

    def __init__(self):
        self.sent: list = []

    def send(self, raw):
        self.sent.append(json.loads(raw))


def _event_frame(topic, data, event_type="Update"):
    return json.dumps([_EVENT, topic, {"data": data, "eventType": event_type}])


def test_dispatch_routes_to_topic_callbacks():
    bus = LcuEventBus(CREDS)
    cs_events, lobby_events = [], []
    bus.subscribe(CHAMP_SELECT_TOPIC, lambda d, e: cs_events.append((d, e)))
    bus.subscribe(LOBBY_TOPIC, lambda d, e: lobby_events.append((d, e)))

    bus._dispatch(_event_frame(CHAMP_SELECT_TOPIC, {"x": 1}, "Create"))
    bus._dispatch(_event_frame(LOBBY_TOPIC, {"y": 2}))

    assert cs_events == [({"x": 1}, "Create")]
    assert lobby_events == [({"y": 2}, "Update")]


def test_dispatch_ignores_non_event_and_unknown_topic():
    bus = LcuEventBus(CREDS)
    seen = []
    bus.subscribe(CHAMP_SELECT_TOPIC, lambda d, e: seen.append(d))

    bus._dispatch(json.dumps([_SUBSCRIBE, CHAMP_SELECT_TOPIC]))  # not an event
    bus._dispatch(_event_frame("OnJsonApiEvent_some_other_topic", {"z": 9}))  # no cb
    bus._dispatch("not json at all")
    assert seen == []


def test_multiple_callbacks_one_topic_and_exception_isolation():
    bus = LcuEventBus(CREDS)
    calls = []

    def boom(d, e):
        raise RuntimeError("handler blew up")

    bus.subscribe(CHAMP_SELECT_TOPIC, boom)
    bus.subscribe(CHAMP_SELECT_TOPIC, lambda d, e: calls.append(d))
    # A raising callback must not prevent the next one from running.
    bus._dispatch(_event_frame(CHAMP_SELECT_TOPIC, {"ok": True}))
    assert calls == [{"ok": True}]


def test_resubscribe_all_sends_every_topic():
    bus = LcuEventBus(CREDS)
    bus.subscribe(CHAMP_SELECT_TOPIC, lambda d, e: None)
    bus.subscribe(LOBBY_TOPIC, lambda d, e: None)
    ws = FakeWS()
    bus._ws = ws
    bus._resubscribe_all()
    topics = {frame[1] for frame in ws.sent if frame[0] == _SUBSCRIBE}
    assert topics == {CHAMP_SELECT_TOPIC, LOBBY_TOPIC}


def test_subscribe_while_connected_sends_immediately():
    bus = LcuEventBus(CREDS)
    ws = FakeWS()
    bus._ws = ws  # simulate an active connection
    bus.subscribe(LOBBY_TOPIC, lambda d, e: None)
    assert [_SUBSCRIBE, LOBBY_TOPIC] in ws.sent
    # A second callback for the same topic does not re-send the subscribe frame.
    bus.subscribe(LOBBY_TOPIC, lambda d, e: None)
    assert sum(1 for f in ws.sent if f == [_SUBSCRIBE, LOBBY_TOPIC]) == 1


def test_champ_select_listener_wraps_bus():
    seen = []
    listener = ChampSelectListener(CREDS, lambda d, e: seen.append((d, e)))
    listener._bus._dispatch(_event_frame(CHAMP_SELECT_TOPIC, {"hover": "Ahri"}, "Update"))
    assert seen == [({"hover": "Ahri"}, "Update")]
