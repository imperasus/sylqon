"""Offline tests for the Discord notifier + match watcher (mocked HTTP/Riot)."""
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.crawler import IngestService
from app.models import Base, Delivery
from app.notifier import DiscordWebhookNotifier, build_embed
from app.watcher import MatchWatcher

from tests.test_store_crawler import make_match, make_riot, make_timeline

PUUID = "puuid-1"


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


class FakeParticipant:
    win = True
    kills, deaths, assists = 5, 2, 7


def make_advice(match_id="EUN1_1"):
    return {
        "match_id": match_id,
        "champion": "Garen",
        "role": "TOP",
        "text": "Tanács szövege.",
    }


# -- notifier -----------------------------------------------------------------


def test_embed_shape_hu():
    payload = build_embed(make_advice(), FakeParticipant(), "hu")
    embed = payload["embeds"][0]
    assert "Garen" in embed["title"] and "Győzelem" in embed["title"] and "5/2/7" in embed["title"]
    assert "Tanács szövege." in embed["description"]
    assert "EUN1_1" in embed["footer"]["text"]


def test_notifier_success_and_429_retry():
    session = MagicMock()
    ok = MagicMock(status_code=204)
    limited = MagicMock(status_code=429, headers={"Retry-After": "1"})
    session.post.side_effect = [limited, ok]
    sleeps = []
    notifier = DiscordWebhookNotifier("https://example/webhook", session=session, sleep=sleeps.append)
    assert notifier.send(make_advice(), FakeParticipant()) is True
    assert sleeps == [1.0]


def test_notifier_disabled_without_url():
    notifier = DiscordWebhookNotifier("")
    assert notifier.enabled is False
    assert notifier.send(make_advice(), FakeParticipant()) is False


def test_notifier_http_error_returns_false():
    session = MagicMock()
    session.post.return_value = MagicMock(status_code=404, text="unknown webhook")
    notifier = DiscordWebhookNotifier("https://example/webhook", session=session)
    assert notifier.send(make_advice(), FakeParticipant()) is False


# -- watcher --------------------------------------------------------------------


def make_watcher(session_factory, riot, sent_results=True):
    notifier = MagicMock(spec=DiscordWebhookNotifier)
    notifier.enabled = True
    notifier.send.return_value = sent_results
    ingest = IngestService(riot, session_factory)
    watcher = MatchWatcher(ingest, session_factory, notifier, puuids=[PUUID], lang="hu")
    return watcher, notifier


def test_first_cycle_baselines_backlog_without_sending(session_factory):
    riot = make_riot(["EUN1_1", "EUN1_2"])
    watcher, notifier = make_watcher(session_factory, riot)
    assert watcher.run_once() == 0
    notifier.send.assert_not_called()
    with session_factory() as s:
        assert s.scalar(select(func.count()).select_from(Delivery)) == 2
        channels = {r[0] for r in s.execute(select(Delivery.channel))}
        assert channels == {"baseline"}


def test_new_match_after_baseline_is_delivered_once(session_factory):
    riot = make_riot(["EUN1_1"])
    watcher, notifier = make_watcher(session_factory, riot)
    watcher.run_once()  # baseline

    new_ids = ["EUN1_2", "EUN1_1"]
    riot.get_match_ids.return_value = new_ids
    riot.get_match.side_effect = lambda mid: make_match(mid)
    riot.get_timeline.side_effect = lambda mid: make_timeline(mid)

    assert watcher.run_once() == 1  # only the new match
    notifier.send.assert_called_once()
    assert notifier.send.call_args.args[0]["match_id"] == "EUN1_2"

    assert watcher.run_once() == 0  # re-poll with same ids: dedupe holds


def test_failed_delivery_is_retried_next_cycle(session_factory):
    riot = make_riot(["EUN1_1"])
    watcher, notifier = make_watcher(session_factory, riot)
    watcher.run_once()  # baseline

    riot.get_match_ids.return_value = ["EUN1_2", "EUN1_1"]
    riot.get_match.side_effect = lambda mid: make_match(mid)
    riot.get_timeline.side_effect = lambda mid: make_timeline(mid)

    notifier.send.return_value = False  # Discord down
    assert watcher.run_once() == 0
    with session_factory() as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(Delivery)
                .where(Delivery.channel == "discord")
            )
            == 0
        )

    notifier.send.return_value = True  # Discord back
    assert watcher.run_once() == 1
