"""Small production security primitives shared by the API application.

The browser is an untrusted client; this module deliberately keeps policy on
the server and never includes implementation details in responses.
"""
from __future__ import annotations

import os
import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse

try:
    from redis.asyncio import Redis
except ImportError:
    Redis = None


def environment() -> str:
    return os.getenv("BISHOPLY_ENV", "development").strip().lower()


def is_production() -> bool:
    return environment() == "production"


def safe_error_response(status_code: int = 500, message: str = "Something went wrong. Please try again."):
    return JSONResponse(status_code=status_code, content={"error": "internal_error", "message": message})


class RequestRateLimiter:
    """Bounded in-memory limiter for sensitive state-changing requests."""

    def __init__(self, limit: int = 120, window_seconds: int = 60):
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        bucket = self._hits[key]
        while bucket and now - bucket[0] >= self.window_seconds:
            bucket.popleft()
        if len(bucket) >= self.limit:
            return False
        bucket.append(now)
        return True


class SharedRateLimiter:
    """Redis-backed limiter for production, bounded memory for local dev."""
    def __init__(self):
        self.memory = RequestRateLimiter()
        self.redis = None
        redis_url = os.getenv("REDIS_URL", "").strip()
        if redis_url:
            if Redis is None:
                raise RuntimeError("redis package is required when REDIS_URL is configured")
            self.redis = Redis.from_url(redis_url, decode_responses=True)

    async def allow(self, key: str, *, limit: int = 120, window_seconds: int = 60) -> bool:
        if self.redis is None:
            if is_production() and os.getenv("BISHOPLY_MULTI_INSTANCE", "false").lower() == "true":
                return False
            return self.memory.allow(key)
        bucket = f"bishoply:ratelimit:{window_seconds}:{limit}:{key}"
        try:
            count = await self.redis.incr(bucket)
            if count == 1:
                await self.redis.expire(bucket, window_seconds)
            return count <= limit
        except Exception:
            # Fail closed in production so a Redis outage cannot remove abuse
            # protection; development remains usable with the memory limiter.
            return False if is_production() else self.memory.allow(key)

    async def close(self):
        if self.redis is not None:
            await self.redis.aclose()


def client_key(request: Request) -> str:
    # Do not trust forwarded headers unless the deployment proxy is explicitly
    # configured to do so; the direct peer is safe for this local service.
    return request.client.host if request.client else "unknown"
