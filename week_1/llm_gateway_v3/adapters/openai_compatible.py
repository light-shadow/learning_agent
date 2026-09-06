"""DeepSeek 与 OpenAI 的 OpenAI Compatible 适配器。"""
from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI

from adapters.base import BaseAdapter
from config import ModelConfig
from errors import GatewayError
from models import InternalRequest, Usage


class OpenAICompatibleAdapter(BaseAdapter):
    """集中处理 OpenAI Compatible 厂商的认证、结构化输出和流式读取。"""

    def _create_client(self, config: ModelConfig) -> AsyncOpenAI:
        api_key = os.getenv(config.api_key_env)
        if not api_key:
            raise GatewayError("gateway_misconfigured", "Gateway 模型凭据未配置", 503)
        options: dict[str, Any] = {"api_key": api_key, "max_retries": 0}
        if config.base_url:
            options["base_url"] = config.base_url
        return AsyncOpenAI(**options)

    @staticmethod
    def _response_format(config: ModelConfig, schema: dict[str, Any] | None) -> dict[str, Any] | None:
        if schema is None:
            return None
        if config.structured_output_mode == "json_schema":
            return {"type": "json_schema", "json_schema": {"name": "gateway_response", "strict": True, "schema": schema}}
        return {"type": "json_object"}

    @staticmethod
    def _messages(request: InternalRequest, config: ModelConfig) -> list[dict[str, str]]:
        messages = [message.model_dump() for message in request.messages]
        if request.response_schema is not None and config.structured_output_mode == "json_object":
            messages.insert(0, {
                "role": "system",
                "content": "只返回一个合法 JSON，必须符合下列 JSON Schema，不要返回 Markdown 或额外文字：" + json.dumps(request.response_schema, ensure_ascii=False),
            })
        return messages

    async def complete(self, config: ModelConfig, request: InternalRequest) -> tuple[str, Usage, str | None]:
        """调用非流式 Chat Completions 并归一化响应。"""
        completion = await self._create_client(config).chat.completions.create(
            model=config.provider_model,
            messages=self._messages(request, config),
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            timeout=request.timeout_seconds,
            response_format=self._response_format(config, request.response_schema),
        )
        message = completion.choices[0].message
        usage = completion.usage
        return (
            message.content or "",
            Usage(
                input_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
                output_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
            ),
            getattr(message, "reasoning_content", None),
        )

    async def stream(self, config: ModelConfig, request: InternalRequest) -> AsyncIterator[dict[str, str]]:
        """调用流式 Chat Completions 并产生统一内容与推理事件。"""
        response = await self._create_client(config).chat.completions.create(
            model=config.provider_model,
            messages=self._messages(request, config),
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            timeout=request.timeout_seconds,
            stream=True,
        )
        async for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                yield {"type": "reasoning", "content": reasoning}
            if delta.content:
                yield {"type": "content", "content": delta.content}
