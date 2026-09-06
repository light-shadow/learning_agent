"""YAML 配置加载、环境变量展开和配置模型。"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, SecretStr, model_validator

_ENV_PATTERN = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)(?::-([^}]*))?}")


def _expand_env(value: object) -> object:
    """递归展开 YAML 中的 ${NAME} 和 ${NAME:-default} 环境变量。"""
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda match: os.getenv(match.group(1), match.group(2) or ""), value)
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    return value


class RetryConfig(BaseModel):
    """定义每条路由的上游重试策略。"""

    max_attempts_per_route: int = Field(default=2, ge=1, le=5)
    base_delay_seconds: float = Field(default=0.25, ge=0, le=10)
    max_delay_seconds: float = Field(default=4, ge=0, le=60)
    retry_statuses: set[int] = {408, 409, 429, 500, 502, 503, 504}


class CircuitBreakerConfig(BaseModel):
    """定义供应商熔断阈值和冷却时间。"""

    failure_threshold: int = Field(default=5, ge=1)
    cooldown_seconds: float = Field(default=30, ge=0)


class RateLimitConfig(BaseModel):
    """定义身份或模型令牌桶的配置。"""

    enabled: bool = True
    requests_per_minute: int = Field(default=60, ge=1)
    burst: int = Field(default=10, ge=1)


class StreamCheckpointConfig(BaseModel):
    """定义可选的流式正文检查点保存策略。"""

    enabled: bool = False
    flush_interval_seconds: float = Field(default=1, ge=0.1, le=60)
    max_chars: int = Field(default=200_000, ge=1_000, le=10_000_000)


class ProviderConfig(BaseModel):
    """描述一个 OpenAI-compatible 或 Anthropic 上游供应商。"""

    protocol: Literal["openai_compatible", "anthropic"] = "openai_compatible"
    base_url: str
    api_key: SecretStr = SecretStr("")
    enabled: bool = True
    timeout_seconds: float = Field(default=120, gt=0)
    connect_timeout_seconds: float = Field(default=10, gt=0)
    extra_headers: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def normalize_url(self) -> "ProviderConfig":
        """移除 Base URL 末尾斜杠，避免调用 URL 出现双斜杠。"""
        self.base_url = self.base_url.rstrip("/")
        return self


class RouteTarget(BaseModel):
    """描述逻辑模型的一条可调用上游路由。"""

    provider: str
    model: str
    weight: int = Field(default=1, ge=1)
    api: Literal["chat", "responses", "both"] = "both"


class ModelRouteConfig(BaseModel):
    """描述一个逻辑模型的路由策略和候选目标。"""

    strategy: Literal["priority", "weighted_round_robin"] = "priority"
    routes: list[RouteTarget] = Field(min_length=1)
    rate_limit: RateLimitConfig | None = None


class PriceConfig(BaseModel):
    """定义真实模型的百万 Token 成本。"""

    input_per_million: float = Field(default=0, ge=0)
    output_per_million: float = Field(default=0, ge=0)
    cached_input_per_million: float | None = Field(default=None, ge=0)


class GatewayConfig(BaseModel):
    """聚合 v4 服务运行所需的所有配置。"""

    service_name: str = "llm-gateway-v4"
    log_file: str = "logs/llm_gateway_v4.log"
    api_keys: list[SecretStr] = Field(default_factory=list)
    database_url: str = "data/gateway.db"
    structured_output_retries: int = Field(default=1, ge=0, le=3)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    identity_rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    model_rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    stream_checkpoint: StreamCheckpointConfig = Field(default_factory=StreamCheckpointConfig)
    providers: dict[str, ProviderConfig]
    models: dict[str, ModelRouteConfig]
    pricing: dict[str, PriceConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_routes(self) -> "GatewayConfig":
        """校验路由引用的供应商存在且 Anthropic 不支持 Responses API。"""
        for alias, model in self.models.items():
            for route in model.routes:
                provider = self.providers.get(route.provider)
                if provider is None:
                    raise ValueError(f"模型 {alias} 引用了未知供应商: {route.provider}")
                if provider.protocol == "anthropic" and route.api in ("responses", "both"):
                    raise ValueError(f"Anthropic 路由 {alias}/{route.provider} 不能声明 Responses API")
        return self


def load_config(path: str | Path | None = None) -> GatewayConfig:
    """加载外部 YAML；未指定时优先使用当前目录 gateway.yaml，否则使用示例文件。"""
    config_path = Path(path or os.getenv("GATEWAY_CONFIG", "gateway.yaml"))
    if not config_path.is_absolute():
        config_path = Path.cwd() / config_path
    if not config_path.exists() and path is None and "GATEWAY_CONFIG" not in os.environ:
        config_path = Path(__file__).resolve().parent.parent / "gateway.example.yaml"
    config = GatewayConfig.model_validate(_expand_env(yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}))
    database_path = Path(config.database_url)
    if not database_path.is_absolute():
        config.database_url = str((config_path.parent / database_path).resolve())
    log_path = Path(config.log_file)
    if not log_path.is_absolute():
        config.log_file = str((config_path.parent / log_path).resolve())
    return config
