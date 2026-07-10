"""Offline tests for the in-memory dual-window token bucket."""
import pytest
from app.ratelimit import InMemoryTokenBucketLimiter, RateLimitTimeout


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def make_limiter(burst=(5, 1.0), sustained=(20, 60.0), max_wait=300.0):
    clock = FakeClock()
    limiter = InMemoryTokenBucketLimiter(
        burst=burst, sustained=sustained, clock=clock, sleep=clock.sleep, max_wait=max_wait
    )
    return limiter, clock


def test_burst_window_allows_permits_up_front():
    limiter, clock = make_limiter()
    start = clock.now
    for _ in range(5):
        limiter.acquire("europe")
    assert clock.now == start  # no waiting for the first burst


def test_burst_exhaustion_waits_for_refill():
    limiter, clock = make_limiter()
    for _ in range(5):
        limiter.acquire("europe")
    start = clock.now
    limiter.acquire("europe")  # 6th permit must wait ~1/5 of the burst window
    assert clock.now - start == pytest.approx(0.2, abs=0.05)


def test_sustained_window_caps_total_throughput():
    # Burst is generous but the sustained window only holds 10 permits/60s.
    limiter, clock = make_limiter(burst=(1000, 1.0), sustained=(10, 60.0))
    start = clock.now
    for _ in range(10):
        limiter.acquire("europe")
    assert clock.now == start
    limiter.acquire("europe")  # 11th → wait for a sustained-window refill
    assert clock.now - start == pytest.approx(6.0, abs=0.5)


def test_penalty_blocks_until_expiry():
    limiter, clock = make_limiter()
    limiter.on_rate_limit_exceeded("europe", retry_after=7.0)
    start = clock.now
    limiter.acquire("europe")
    assert clock.now - start >= 7.0


def test_penalty_does_not_shrink_existing_penalty():
    limiter, clock = make_limiter()
    limiter.on_rate_limit_exceeded("europe", retry_after=10.0)
    limiter.on_rate_limit_exceeded("europe", retry_after=1.0)  # ignored — shorter
    start = clock.now
    limiter.acquire("europe")
    assert clock.now - start >= 10.0


def test_routing_keys_have_independent_budgets():
    limiter, clock = make_limiter()
    for _ in range(5):
        limiter.acquire("europe")
    start = clock.now
    limiter.acquire("euw1")  # different routing key — fresh bucket, no wait
    assert clock.now == start


def test_wait_ceiling_raises():
    limiter, _ = make_limiter(burst=(1, 3600.0), sustained=(1, 3600.0), max_wait=5.0)
    limiter.acquire("europe")
    with pytest.raises(RateLimitTimeout):
        limiter.acquire("europe")
