"""Dual-window token-bucket rate limiter for the Riot API.

Two implementations behind one interface:

- ``RedisTokenBucketLimiter`` — a single atomic Lua script per acquire attempt;
  state keyed by API-key hash + routing region, so multiple workers/instances
  share one budget (matching how Riot actually scopes limits).
- ``InMemoryTokenBucketLimiter`` — same math against an injected clock; used by
  unit tests and as a no-Redis fallback (single-process budget only).

Both windows (burst + sustained) must have a token before a request may go out.
A 429 from Riot installs a shared penalty so every worker backs off together.
"""
from __future__ import annotations

import hashlib
import random
import threading
import time
from dataclasses import dataclass

from app import config

_LUA_ACQUIRE = """
local burst_key = KEYS[1]
local sust_key = KEYS[2]
local penalty_key = KEYS[3]
local now_ms = tonumber(ARGV[1])
local burst_permits = tonumber(ARGV[2])
local burst_window_ms = tonumber(ARGV[3])
local sust_permits = tonumber(ARGV[4])
local sust_window_ms = tonumber(ARGV[5])

if redis.call('EXISTS', penalty_key) == 1 then
  local ttl = redis.call('PTTL', penalty_key)
  if ttl > 0 then return ttl end
end

local function refill(key, permits, window_ms)
  local state = redis.call('HMGET', key, 'tokens', 'ts')
  local tokens = tonumber(state[1])
  local ts = tonumber(state[2])
  if tokens == nil then
    tokens = permits
    ts = now_ms
  else
    local elapsed = math.max(0, now_ms - ts)
    tokens = math.min(permits, tokens + elapsed * (permits / window_ms))
    ts = now_ms
  end
  return tokens, ts
end

local b_tokens, b_ts = refill(burst_key, burst_permits, burst_window_ms)
local s_tokens, s_ts = refill(sust_key, sust_permits, sust_window_ms)

if b_tokens >= 1 and s_tokens >= 1 then
  redis.call('HMSET', burst_key, 'tokens', b_tokens - 1, 'ts', b_ts)
  redis.call('PEXPIRE', burst_key, burst_window_ms * 2)
  redis.call('HMSET', sust_key, 'tokens', s_tokens - 1, 'ts', s_ts)
  redis.call('PEXPIRE', sust_key, sust_window_ms * 2)
  return 0
end

redis.call('HMSET', burst_key, 'tokens', b_tokens, 'ts', b_ts)
redis.call('PEXPIRE', burst_key, burst_window_ms * 2)
redis.call('HMSET', sust_key, 'tokens', s_tokens, 'ts', s_ts)
redis.call('PEXPIRE', sust_key, sust_window_ms * 2)

local wait_b = 0
if b_tokens < 1 then
  wait_b = math.ceil((1 - b_tokens) * (burst_window_ms / burst_permits))
end
local wait_s = 0
if s_tokens < 1 then
  wait_s = math.ceil((1 - s_tokens) * (sust_window_ms / sust_permits))
end
return math.max(wait_b, wait_s, 1)
"""


class RateLimitTimeout(Exception):
    """Raised when a permit could not be acquired within the wait ceiling."""


class RateLimiter:
    """Interface: blocking acquire + 429 feedback."""

    def acquire(self, routing_key: str) -> None:
        raise NotImplementedError

    def on_rate_limit_exceeded(self, routing_key: str, retry_after: float) -> None:
        raise NotImplementedError


@dataclass
class _Bucket:
    permits: int
    window_s: float
    tokens: float
    ts: float

    def refill(self, now: float) -> None:
        elapsed = max(0.0, now - self.ts)
        self.tokens = min(float(self.permits), self.tokens + elapsed * (self.permits / self.window_s))
        self.ts = now

    def wait_for_one(self) -> float:
        if self.tokens >= 1:
            return 0.0
        return (1 - self.tokens) * (self.window_s / self.permits)


class InMemoryTokenBucketLimiter(RateLimiter):
    def __init__(
        self,
        burst: tuple[int, float] | None = None,
        sustained: tuple[int, float] | None = None,
        clock=time.monotonic,
        sleep=time.sleep,
        max_wait: float | None = None,
    ) -> None:
        self._clock = clock
        self._sleep = sleep
        self._max_wait = max_wait if max_wait is not None else config.RATE_LIMIT_MAX_WAIT
        b_permits, b_window = burst or config.RATE_LIMIT_BURST
        s_permits, s_window = sustained or config.RATE_LIMIT_SUSTAINED
        self._lock = threading.Lock()
        self._buckets: dict[str, tuple[_Bucket, _Bucket]] = {}
        self._penalty_until: dict[str, float] = {}
        self._burst_spec = (b_permits, b_window)
        self._sustained_spec = (s_permits, s_window)

    def _pair(self, key: str) -> tuple[_Bucket, _Bucket]:
        pair = self._buckets.get(key)
        if pair is None:
            now = self._clock()
            b, bw = self._burst_spec
            s, sw = self._sustained_spec
            pair = (_Bucket(b, bw, float(b), now), _Bucket(s, sw, float(s), now))
            self._buckets[key] = pair
        return pair

    def _try_acquire(self, key: str) -> float:
        """Returns 0 on success, otherwise seconds to wait."""
        with self._lock:
            now = self._clock()
            penalty_until = self._penalty_until.get(key, 0.0)
            if penalty_until > now:
                return penalty_until - now
            burst, sustained = self._pair(key)
            burst.refill(now)
            sustained.refill(now)
            if burst.tokens >= 1 and sustained.tokens >= 1:
                burst.tokens -= 1
                sustained.tokens -= 1
                return 0.0
            return max(burst.wait_for_one(), sustained.wait_for_one(), 0.001)

    def acquire(self, routing_key: str) -> None:
        waited = 0.0
        while True:
            wait = self._try_acquire(routing_key)
            if wait <= 0:
                return
            if waited + wait > self._max_wait:
                raise RateLimitTimeout(
                    f"rate-limit wait exceeded {self._max_wait}s for {routing_key}"
                )
            self._sleep(wait)
            waited += wait

    def on_rate_limit_exceeded(self, routing_key: str, retry_after: float) -> None:
        with self._lock:
            until = self._clock() + max(0.0, retry_after)
            if until > self._penalty_until.get(routing_key, 0.0):
                self._penalty_until[routing_key] = until


class RedisTokenBucketLimiter(RateLimiter):
    def __init__(
        self,
        redis_client=None,
        burst: tuple[int, float] | None = None,
        sustained: tuple[int, float] | None = None,
        api_key: str | None = None,
        max_wait: float | None = None,
        sleep=time.sleep,
    ) -> None:
        if redis_client is None:
            import redis as _redis

            redis_client = _redis.Redis.from_url(config.REDIS_URL)
        self._redis = redis_client
        self._script = self._redis.register_script(_LUA_ACQUIRE)
        self._burst = burst or config.RATE_LIMIT_BURST
        self._sustained = sustained or config.RATE_LIMIT_SUSTAINED
        self._max_wait = max_wait if max_wait is not None else config.RATE_LIMIT_MAX_WAIT
        self._sleep = sleep
        key = api_key if api_key is not None else config.RIOT_API_KEY
        self._key_hash = hashlib.sha256(key.encode()).hexdigest()[:12]

    def _keys(self, routing_key: str) -> list[str]:
        prefix = f"rl:{self._key_hash}:{routing_key}"
        return [f"{prefix}:burst", f"{prefix}:sustained", f"{prefix}:penalty"]

    def acquire(self, routing_key: str) -> None:
        b_permits, b_window = self._burst
        s_permits, s_window = self._sustained
        waited = 0.0
        while True:
            wait_ms = int(
                self._script(
                    keys=self._keys(routing_key),
                    args=[
                        int(time.time() * 1000),
                        b_permits,
                        int(b_window * 1000),
                        s_permits,
                        int(s_window * 1000),
                    ],
                )
            )
            if wait_ms <= 0:
                return
            wait = wait_ms / 1000 + random.uniform(0, 0.05)
            if waited + wait > self._max_wait:
                raise RateLimitTimeout(
                    f"rate-limit wait exceeded {self._max_wait}s for {routing_key}"
                )
            self._sleep(wait)
            waited += wait

    def on_rate_limit_exceeded(self, routing_key: str, retry_after: float) -> None:
        penalty_key = self._keys(routing_key)[2]
        self._redis.set(penalty_key, 1, px=max(1, int(retry_after * 1000)), nx=True)


def build_rate_limiter() -> RateLimiter:
    if config.RATELIMIT_MODE == "memory":
        return InMemoryTokenBucketLimiter()
    return RedisTokenBucketLimiter()
