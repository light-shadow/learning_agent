# resilience/retry.py
import asyncio
from functools import wraps
from typing import Callable, Type, Union
import logging

logger = logging.getLogger(__name__)

def async_retry(max_attempts: int = 3, base_delay: float = 1.0, max_delay: float = 10.0, exponential_base: float = 2):
    """指数退避重试装饰器（用于异步函数）"""
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            delay = base_delay
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    # 仅对可重试错误重试（如 5xx, 429）
                    if not is_retryable(e):
                        raise
                    if attempt == max_attempts:
                        break
                    logger.warning(f"Attempt {attempt} failed: {e}, retrying in {delay}s")
                    await asyncio.sleep(delay)
                    delay = min(delay * exponential_base, max_delay)
            raise last_exception
        return wrapper
    return decorator

def is_retryable(exc):
    """判断异常是否可重试：根据HTTP状态码或异常类型"""
    # 如果异常有 status_code 属性，检查是否为 429 或 5xx
    if hasattr(exc, 'status_code'):
        return exc.status_code in (429, 500, 502, 503, 504)
    # 否则假定可重试（保守）
    return True