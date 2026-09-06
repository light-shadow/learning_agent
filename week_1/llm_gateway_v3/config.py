"""LLM Gateway v3 的模型、限流和审计配置。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal


ProviderType = Literal["deepseek", "openai", "anthropic"]
StructuredOutputMode = Literal["json_schema", "json_object", "prompt"]


@dataclass(frozen=True)
class ModelConfig:
    """描述一个对外逻辑模型到供应商模型的完整映射关系。"""

    provider: ProviderType
    provider_model: str
    base_url: str | None
    api_key_env: str
    supports_structured_output: bool
    structured_output_mode: StructuredOutputMode
    fallback_model: str | None
    rate_limit_per_minute: int
    input_price_per_million: float
    output_price_per_million: float


MODEL_CONFIGS: dict[str, ModelConfig] = {
    "deepseek-v4-pro": ModelConfig(
        provider="deepseek",
        provider_model=os.getenv("DEEPSEEK_V4_PRO_MODEL", "deepseek-v4-pro"),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        api_key_env="DEEPSEEK_API_KEY",
        supports_structured_output=True,
        structured_output_mode="json_object",
        fallback_model="deepseek-v4-flash",
        rate_limit_per_minute=int(os.getenv("DEEPSEEK_V4_PRO_RPM", "100")),
        input_price_per_million=float(os.getenv("DEEPSEEK_V4_PRO_INPUT_PRICE", "1.0")),
        output_price_per_million=float(os.getenv("DEEPSEEK_V4_PRO_OUTPUT_PRICE", "4.0")),
    ),
    "deepseek-v4-flash": ModelConfig(
        provider="deepseek",
        provider_model=os.getenv("DEEPSEEK_V4_FLASH_MODEL", "deepseek-v4-flash"),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        api_key_env="DEEPSEEK_API_KEY",
        supports_structured_output=True,
        structured_output_mode="json_object",
        fallback_model=None,
        rate_limit_per_minute=int(os.getenv("DEEPSEEK_V4_FLASH_RPM", "120")),
        input_price_per_million=float(os.getenv("DEEPSEEK_V4_FLASH_INPUT_PRICE", "0.8")),
        output_price_per_million=float(os.getenv("DEEPSEEK_V4_FLASH_OUTPUT_PRICE", "3.2")),
    ),
    # 以下两项默认不在演示请求中使用，填入对应环境变量后即可启用。
    "openai-general": ModelConfig(
        provider="openai",
        provider_model=os.getenv("OPENAI_GENERAL_MODEL", "gpt-4.1-mini"),
        base_url=os.getenv("OPENAI_BASE_URL") or None,
        api_key_env="OPENAI_API_KEY",
        supports_structured_output=True,
        structured_output_mode="json_schema",
        fallback_model=None,
        rate_limit_per_minute=int(os.getenv("OPENAI_GENERAL_RPM", "60")),
        input_price_per_million=float(os.getenv("OPENAI_GENERAL_INPUT_PRICE", "0")),
        output_price_per_million=float(os.getenv("OPENAI_GENERAL_OUTPUT_PRICE", "0")),
    ),
    "anthropic-general": ModelConfig(
        provider="anthropic",
        provider_model=os.getenv("ANTHROPIC_GENERAL_MODEL", "claude-3-5-haiku-latest"),
        base_url=os.getenv("ANTHROPIC_BASE_URL") or None,
        api_key_env="ANTHROPIC_API_KEY",
        supports_structured_output=True,
        structured_output_mode="prompt",
        fallback_model=None,
        rate_limit_per_minute=int(os.getenv("ANTHROPIC_GENERAL_RPM", "60")),
        input_price_per_million=float(os.getenv("ANTHROPIC_GENERAL_INPUT_PRICE", "0")),
        output_price_per_million=float(os.getenv("ANTHROPIC_GENERAL_OUTPUT_PRICE", "0")),
    ),
}

MAX_TRACE_RECORDS = int(os.getenv("LLM_GATEWAY_MAX_TRACE_RECORDS", "1000"))
MAX_ATTEMPTS_PER_MODEL = 2
