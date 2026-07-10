"""Integration tests for the Redis/Lua token bucket.

Skipped automatically when no Redis is reachable on REDIS_URL (CI and the live
verification run them; plain offline runs skip).
"""
import time
import uuid

import pytest
from app.ratelimit import RateLimitTimeout, RedisTokenBucketLimiter


def _redis_or_skip():
    redis = pytest.importorskip("redis")
    client = redis.Redis.from_url("redis://localhost:6379/0", socket_connect_timeout=1)
    try:
        client.ping()
    except Exception:
        pytest.skip("no Redis reachable on localhost:6379")
    return client


def make_limiter(client, burst=(5, 1.0), sustained=(50, 60.0), max_wait=10.0):
    sleeps: list[float] = []

    def recording_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        time.sleep(min(seconds, 0.3))

    limiter = RedisTokenBucketLimiter(
        redis_client=client,
        burst=burst,
        sustained=sustained,
        api_key=f"test-{uuid.uuid4()}",  # unique hash → isolated keys per test
        max_wait=max_wait,
        sleep=recording_sleep,
    )
    return limiter, sleeps


def test_burst_permits_then_wait():
    client = _redis_or_skip()
    limiter, sleeps = make_limiter(client)
    for _ in range(5):
        limiter.acquire("europe")
    assert sleeps == []  # burst went through without waiting
    limiter.acquire("europe")  # 6th → Lua returns a wait
    assert len(sleeps) >= 1
    assert 0 < sleeps[0] < 1.0


def test_penalty_key_blocks_all_workers():
    client = _redis_or_skip()
    limiter, sleeps = make_limiter(client)
    limiter.on_rate_limit_exceeded("europe", retry_after=0.5)
    limiter.acquire("europe")
    assert sleeps and sleeps[0] >= 0.4  # waited out the penalty PTTL


def test_wait_ceiling_raises():
    client = _redis_or_skip()
    limiter, _ = make_limiter(client, burst=(1, 3600.0), sustained=(1, 3600.0), max_wait=0.5)
    limiter.acquire("europe")
    with pytest.raises(RateLimitTimeout):
        limiter.acquire("europe")
