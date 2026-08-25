"""What the limiter promises, and what it gives up.

R-034. The interesting cases are the two it is easiest to get wrong: a Redis
that is unreachable, and a window that has rolled over.
"""

from __future__ import annotations

import pytest
from koras_ratelimit import RateLimit, check, window_key


class FakeRedis:
    """Counts in a dict. Enough for INCR and EXPIRE, which is all this uses."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.expiries: dict[str, int] = {}

    async def incr(self, name: str) -> int:
        self.counts[name] = self.counts.get(name, 0) + 1
        return self.counts[name]

    async def expire(self, name: str, seconds: int) -> bool:
        self.expiries[name] = seconds
        return True


class BrokenRedis:
    async def incr(self, name: str) -> int:
        raise ConnectionError("connection refused")

    async def expire(self, name: str, seconds: int) -> bool:
        raise ConnectionError("connection refused")


LIMIT = RateLimit(limit=3, window_seconds=60)


@pytest.mark.asyncio
async def test_allows_up_to_the_limit() -> None:
    redis = FakeRedis()
    for expected_remaining in (2, 1, 0):
        decision = await check(redis, bucket="anon", identity="a", limit=LIMIT, now=1000.0)
        assert decision.allowed
        assert decision.remaining == expected_remaining


@pytest.mark.asyncio
async def test_refuses_past_the_limit() -> None:
    redis = FakeRedis()
    for _ in range(3):
        await check(redis, bucket="anon", identity="a", limit=LIMIT, now=1000.0)

    decision = await check(redis, bucket="anon", identity="a", limit=LIMIT, now=1000.0)
    assert not decision.allowed
    assert decision.headers["Retry-After"]
    assert decision.headers["RateLimit-Remaining"] == "0"


@pytest.mark.asyncio
async def test_one_caller_cannot_spend_another_quota() -> None:
    redis = FakeRedis()
    for _ in range(4):
        await check(redis, bucket="anon", identity="noisy", limit=LIMIT, now=1000.0)

    decision = await check(redis, bucket="anon", identity="quiet", limit=LIMIT, now=1000.0)
    assert decision.allowed, "one caller exhausting its quota refused another"


@pytest.mark.asyncio
async def test_buckets_are_independent() -> None:
    # The unauthenticated tier and the per-tenant tier must not share a counter,
    # or passing through the first would consume the second.
    redis = FakeRedis()
    for _ in range(4):
        await check(redis, bucket="anon", identity="a", limit=LIMIT, now=1000.0)

    decision = await check(redis, bucket="tenant", identity="a", limit=LIMIT, now=1000.0)
    assert decision.allowed


@pytest.mark.asyncio
async def test_the_window_rolls_over() -> None:
    redis = FakeRedis()
    for _ in range(4):
        await check(redis, bucket="anon", identity="a", limit=LIMIT, now=1000.0)

    later = await check(redis, bucket="anon", identity="a", limit=LIMIT, now=1000.0 + 60)
    assert later.allowed, "the quota did not reset in the next window"


@pytest.mark.asyncio
async def test_an_unreachable_redis_allows_and_says_so() -> None:
    # Fails open on purpose: a limiter outage must not become a total outage.
    # `degraded` is how a caller can tell that nothing is being limited, which
    # is the part that must never be silent.
    decision = await check(BrokenRedis(), bucket="anon", identity="a", limit=LIMIT)
    assert decision.allowed
    assert decision.degraded


@pytest.mark.asyncio
async def test_no_redis_configured_allows_and_says_so() -> None:
    decision = await check(None, bucket="anon", identity="a", limit=LIMIT)
    assert decision.allowed
    assert decision.degraded


@pytest.mark.asyncio
async def test_every_request_carries_the_quota() -> None:
    # Not only the refusals: a caller that learns its limit only by exceeding it
    # has to exceed it to learn anything.
    decision = await check(FakeRedis(), bucket="anon", identity="a", limit=LIMIT, now=1000.0)
    assert decision.headers["RateLimit-Limit"] == "3"
    assert "Retry-After" not in decision.headers


@pytest.mark.asyncio
async def test_the_key_always_gets_a_ttl() -> None:
    # EXPIRE on every request rather than only when the count is 1. The
    # count == 1 form loses the race where two callers INCR before either
    # EXPIREs, leaving a key with no TTL and a caller limited forever.
    redis = FakeRedis()
    await check(redis, bucket="anon", identity="a", limit=LIMIT, now=1000.0)
    await check(redis, bucket="anon", identity="a", limit=LIMIT, now=1000.0)
    assert set(redis.expiries.values()) == {60}


def test_the_window_key_changes_with_the_window() -> None:
    # Window 16 spans [960, 1020). 1000 and 1010 fall inside it; 1030 does not.
    # The first draft of this test used 1030 as the "same" case and failed --
    # which is the boundary arithmetic the fixed window is built on, so getting
    # it wrong here is worth keeping a note about.
    first = window_key("anon", "a", 60, 1000.0)
    same = window_key("anon", "a", 60, 1010.0)
    later = window_key("anon", "a", 60, 1030.0)
    assert first == same
    assert first != later


def test_a_nonsense_limit_is_refused_at_construction() -> None:
    # Better here than as a quota of zero that refuses every request in
    # production, which looks like an outage rather than a misconfiguration.
    with pytest.raises(ValueError):
        RateLimit(limit=0, window_seconds=60)
    with pytest.raises(ValueError):
        RateLimit(limit=10, window_seconds=0)
