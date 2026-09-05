# resilience/rate_limiter.py
import time
from collections import defaultdict
from threading import Lock
from config import RATE_LIMITS

class RateLimiter:
    """基于令牌桶的限流器（内存实现）"""
    def __init__(self, limits=None):
        """初始化限流器，可传入独立限流配置用于测试。"""
        self.limits = limits if limits is not None else RATE_LIMITS  # {model: requests_per_minute}
        self.tokens = defaultdict(float)
        self.last_update = defaultdict(float)
        self.lock = Lock()

    def _get_limit(self, model: str) -> int:
        return self.limits.get(model, 60)  # 默认60

    def _refill(self, model: str, now: float):
        """补充令牌"""
        limit = self._get_limit(model)
        tokens_per_sec = limit / 60.0
        elapsed = now - self.last_update[model]
        self.tokens[model] = min(limit, self.tokens[model] + elapsed * tokens_per_sec)
        self.last_update[model] = now

    def allow_request(self, model: str) -> bool:
        """返回是否允许请求，若允许则消耗一个令牌"""
        with self.lock:
            now = time.time()
            self._refill(model, now)
            if self.tokens[model] >= 1:
                self.tokens[model] -= 1
                return True
            return False

# 全局单例
rate_limiter = RateLimiter()
