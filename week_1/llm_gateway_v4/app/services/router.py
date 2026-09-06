"""逻辑模型路由、加权轮询和供应商熔断。"""
from __future__ import annotations

import itertools
import time
from dataclasses import dataclass

from app.config import GatewayConfig, RouteTarget
from app.core.errors import GatewayError


@dataclass
class CircuitState:
    """记录一个供应商连续失败次数及熔断开启时间。"""

    failures: int = 0
    opened_at: float | None = None


class ModelRouter:
    """选择满足 API 能力且未熔断的候选上游路由。"""

    def __init__(self, config: GatewayConfig) -> None:
        self.config = config
        self._circuits: dict[str, CircuitState] = {}
        self._counters: dict[str, itertools.count] = {}

    def candidates(self, alias: str, api: str) -> list[RouteTarget]:
        """返回按策略排序的健康路由；不存在或无健康路由时抛错。"""
        route_config = self.config.models.get(alias)
        if route_config is None:
            raise GatewayError("模型别名不存在", status_code=404, code="model_not_found", error_type="invalid_request_error")
        available = [route for route in route_config.routes if self.config.providers[route.provider].enabled and route.api in (api, "both") and self._available(route.provider)]
        if not available:
            raise GatewayError("没有可用的模型路由", status_code=503, code="no_healthy_route", error_type="service_unavailable_error")
        if route_config.strategy == "priority":
            return available
        weighted = [route for route in available for _ in range(route.weight)]
        counter = self._counters.setdefault(alias, itertools.count())
        primary = weighted[next(counter) % len(weighted)]
        return [primary, *[route for route in available if route != primary]]

    def record_success(self, provider: str) -> None:
        """成功调用后清空供应商的熔断失败状态。"""
        self._circuits[provider] = CircuitState()

    def record_failure(self, provider: str) -> None:
        """累计失败次数，达到配置阈值时打开熔断器。"""
        state = self._circuits.setdefault(provider, CircuitState())
        state.failures += 1
        if state.failures >= self.config.circuit_breaker.failure_threshold:
            state.opened_at = time.monotonic()

    def _available(self, provider: str) -> bool:
        state = self._circuits.get(provider)
        if state is None or state.opened_at is None:
            return True
        if time.monotonic() - state.opened_at >= self.config.circuit_breaker.cooldown_seconds:
            self._circuits[provider] = CircuitState()
            return True
        return False

    def status(self) -> dict[str, dict[str, object]]:
        """返回熔断状态，供管理员接口检查。"""
        return {name: {"failures": state.failures, "open": state.opened_at is not None and not self._available(name)} for name, state in self._circuits.items()}
