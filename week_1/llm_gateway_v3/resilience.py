"""限流和上游异常分类。"""
from __future__ import annotations

import time
from threading import Lock

from openai import APIConnectionError, APITimeoutError, RateLimitError


class RateLimiter:
    """提供按逻辑模型隔离的进程内令牌桶限流能力。"""

    def __init__(self, limits: dict[str, int]) -> None:
        self._limits = limits
        self._tokens: dict[str, float] = {}
        self._last_updated: dict[str, float] = {}
        self._lock = Lock()

    def allow_request(self, model: str) -> bool:
        """在有可用令牌时允许本次入口请求并扣减一个令牌。"""
        with self._lock:
            limit = self._limits.get(model, 60)
            now = time.monotonic()
            if model not in self._tokens:
                self._tokens[model] = float(limit)
                self._last_updated[model] = now
            elapsed = now - self._last_updated[model]
            self._tokens[model] = min(float(limit), self._tokens[model] + elapsed * limit / 60)
            self._last_updated[model] = now
            if self._tokens[model] < 1:
                return False
            self._tokens[model] -= 1
            return True


def is_retryable(exc: Exception) -> bool:
    """只将连接、超时、限流和明确的上游 5xx 视为可重试错误。"""
    if isinstance(exc, (APIConnectionError, APITimeoutError, RateLimitError, TimeoutError, ConnectionError)):
        return True
    status_code = getattr(exc, "status_code", None)
    return status_code in (429, 500, 502, 503, 504)
