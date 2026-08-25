"""Request rate limiting, held in Redis.

R-034. The API had no limiter of any kind: no per-caller quota, no per-tenant
quota, nothing in front of the token-verification path — which is reachable
without credentials by definition and is the most expensive thing the service
does, being a JWKS lookup and an asymmetric signature check.

Two decisions shape everything here.

**The counter lives in Redis, not in the process.** The API runs more than one
machine, and an in-process counter is a per-machine counter: it multiplies the
real limit by however many machines happen to be up, and the limit silently
loosens every time the service scales out. Each environment already has its own
Upstash database, provisioned per environment and never shared, which is the
right store and the right isolation boundary.

**It fails open.** If Redis cannot be reached the request is allowed, loudly.
The alternative makes Redis a hard dependency of every request, so a limiter
outage becomes a total outage — the same trade the JWKS cache in `koras_auth`
already refuses for the identity provider. A limiter exists to blunt abuse, and
trading all availability for some abuse resistance is the wrong way round.

The consequence is stated rather than hidden: while Redis is down there is no
rate limiting, and nothing but the log says so. `RateLimitDecision.degraded`
carries it so a caller can surface it as a metric and alert on it, because a
protection that silently stops protecting is worse than one that was never
there.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Protocol

_log = logging.getLogger(__name__)


class RedisLike(Protocol):
    """The two commands this needs, so a test can supply them without a server."""

    async def incr(self, name: str) -> int: ...

    async def expire(self, name: str, seconds: int) -> bool: ...


@dataclass(frozen=True)
class RateLimit:
    """A quota: `limit` requests per `window_seconds`."""

    limit: int
    window_seconds: int

    def __post_init__(self) -> None:
        if self.limit < 1:
            raise ValueError("limit must be at least 1")
        if self.window_seconds < 1:
            raise ValueError("window_seconds must be at least 1")


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    """Seconds until the current window resets. Sent as Retry-After on a 429."""
    reset_seconds: int
    """True when Redis could not be reached and the request was allowed anyway."""
    degraded: bool = False

    @property
    def headers(self) -> dict[str, str]:
        """Standard rate-limit headers, for allowed and refused alike.

        A caller that only learns its quota by exceeding it has to exceed it to
        learn anything, so these go on every response rather than on the 429.
        """
        out = {
            "RateLimit-Limit": str(self.limit),
            "RateLimit-Remaining": str(max(0, self.remaining)),
            "RateLimit-Reset": str(self.reset_seconds),
        }
        if not self.allowed:
            out["Retry-After"] = str(self.reset_seconds)
        return out


def window_key(bucket: str, identity: str, window_seconds: int, now: float) -> str:
    """The Redis key for one caller in one window.

    A fixed window rather than a sliding one. It is a single INCR — one round
    trip, atomic without a script — where a sliding window needs a sorted set,
    a range delete and a count.

    The known weakness is the boundary: a caller can spend its whole quota at
    the end of one window and again at the start of the next, so the true
    short-term ceiling is twice the limit. That is acceptable for abuse control
    and would not be for billing. Stated here because the next person to read
    this will otherwise have to rediscover it.
    """
    window = int(now // window_seconds)
    return f"ratelimit:{bucket}:{identity}:{window}"


async def check(
    redis: RedisLike | None,
    *,
    bucket: str,
    identity: str,
    limit: RateLimit,
    now: float | None = None,
) -> RateLimitDecision:
    """Count this request and say whether it is allowed.

    `bucket` separates independent quotas — the unauthenticated tier from the
    per-tenant one — so that exhausting one does not consume the other.
    `identity` is who is being limited within that bucket.
    """
    moment = time.time() if now is None else now
    elapsed = moment % limit.window_seconds
    reset = int(limit.window_seconds - elapsed) or limit.window_seconds

    if redis is None:
        return RateLimitDecision(
            allowed=True,
            limit=limit.limit,
            remaining=limit.limit,
            reset_seconds=reset,
            degraded=True,
        )

    key = window_key(bucket, identity, limit.window_seconds, moment)

    try:
        count = await redis.incr(key)
        # Set on every request rather than only when count == 1. The
        # count == 1 form loses the race where two callers INCR before either
        # EXPIREs: one key then has no TTL and the caller is limited forever.
        # EXPIRE is idempotent and costs one pipelined round trip.
        await redis.expire(key, limit.window_seconds)
    except Exception as exc:  # noqa: BLE001 - any client failure means the same thing
        # Never the key or the identity: this line is a log record, and the
        # identity is a user id.
        _log.warning("rate limiter unavailable, allowing request: %s", type(exc).__name__)
        return RateLimitDecision(
            allowed=True,
            limit=limit.limit,
            remaining=limit.limit,
            reset_seconds=reset,
            degraded=True,
        )

    return RateLimitDecision(
        allowed=count <= limit.limit,
        limit=limit.limit,
        remaining=limit.limit - count,
        reset_seconds=reset,
    )
