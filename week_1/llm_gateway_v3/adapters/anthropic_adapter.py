"""Anthropic Messages API 适配器。"""
from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

from adapters.base import BaseAdapter
from config import ModelConfig
from errors import GatewayError
from models import InternalRequest, Usage


class AnthropicAdapter(BaseAdapter):
    """将内部请求转换为 Anthropic Messages API 请求。"""

    def _create_client(self, config: ModelConfig) -> Any:
        api_key = os.getenv(config.api_key_env)
        if not api_key:
            raise GatewayError("gateway_misconfigured", "Gateway 模型凭据未配置", 503)
        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:
            raise GatewayError("gateway_misconfigured", "未安装 anthropic 依赖", 503) from exc
        options: dict[str, Any] = {"api_key": api_key}
        if config.base_url:
            options["base_url"] = config.base_url
        return AsyncAnthropic(**options)

    @staticmethod
    def _messages(request: InternalRequest) -> tuple[str | None, list[dict[str, str]]]:
        system_parts = [message.content for message in request.messages if message.role == "system"]
        messages = [message.model_dump() for message in request.messages if message.role != "system"]
        if request.response_schema is not None:
            constraint = "只返回一个合法 JSON，必须符合下列 JSON Schema，不要返回 Markdown 或额外文字：" + json.dumps(request.response_schema, ensure_ascii=False)
            if messages and messages[-1]["role"] == "user":
                messages[-1]["content"] += "\n\n" + constraint
            else:
                messages.append({"role": "user", "content": constraint})
        return "\n\n".join(system_parts) or None, messages

    async def complete(self, config: ModelConfig, request: InternalRequest) -> tuple[str, Usage, str | None]:
        """调用 Anthropic 非流式接口并归一化 Token 用量。"""
        system, messages = self._messages(request)
        response = await self._create_client(config).messages.create(
            model=config.provider_model,
            system=system,
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            timeout=request.timeout_seconds,
        )
        content = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
        return content, Usage(input_tokens=response.usage.input_tokens, output_tokens=response.usage.output_tokens), None

    async def stream(self, config: ModelConfig, request: InternalRequest) -> AsyncIterator[dict[str, str]]:
        """调用 Anthropic 流式接口并提取文本增量事件。"""
        system, messages = self._messages(request)
        client = self._create_client(config)
        async with client.messages.stream(
            model=config.provider_model,
            system=system,
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            timeout=request.timeout_seconds,
        ) as stream:
            async for text in stream.text_stream:
                yield {"type": "content", "content": text}
