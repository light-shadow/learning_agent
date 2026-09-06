"""进程内异步令牌桶限流器。"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from app.config import RateLimitConfig
from app.core.errors import GatewayError


@dataclass
class Bucket:
    """保存一个限流维度的剩余令牌和更新时间。"""

    tokens: float
    updated_at: float


class InMemoryRateLimiter:
    """按传入键隔离的单进程异步令牌桶。"""

    def __init__(self, config: RateLimitConfig) -> None:
        self.config = config
        self._buckets: dict[str, Bucket] = {}
        self._lock = asyncio.Lock()

    async def check(self, key: str, override: RateLimitConfig | None = None) -> None:
        """消耗一个令牌，超过容量时抛出带 Retry-After 的限流错误。"""
        config = override or self.config
        if not config.enabled:
            return
        now = time.monotonic()
        async with self._lock:
            bucket = self._buckets.setdefault(key, Bucket(float(config.burst), now))
            refill = config.requests_per_minute / 60
            bucket.tokens = min(float(config.burst), bucket.tokens + (now - bucket.updated_at) * refill)
            bucket.updated_at = now
            if bucket.tokens < 1:
                raise GatewayError("请求频率超限", status_code=429, code="rate_limit_exceeded", error_type="rate_limit_error")
            bucket.tokens -= 1
