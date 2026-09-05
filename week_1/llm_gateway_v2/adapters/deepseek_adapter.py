"""DeepSeek OpenAI 兼容接口适配器。"""

import time
from typing import Any, AsyncGenerator, Dict, List

from openai import AsyncOpenAI

from adapters.base import BaseAdapter
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL
from models import ChatRequest, ChatResponse, UsageInfo


class DeepSeekAdapter(BaseAdapter):
    """将统一聊天请求转换为 DeepSeek Chat Completions 请求。"""

    def __init__(
        self,
        model_name: str,
        api_key: str = DEEPSEEK_API_KEY,
        base_url: str = DEEPSEEK_BASE_URL,
    ):
        super().__init__(model_name, api_key)
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    @staticmethod
    def _build_messages(request: ChatRequest) -> List[Dict[str, str]]:
        """将 Pydantic 消息模型序列化为 DeepSeek 接口需要的 JSON 结构。"""
        return [message.model_dump(mode="json") for message in request.messages]

    @staticmethod
    def _build_usage(usage: Any) -> UsageInfo:
        """将上游用量对象归一化为网关的 UsageInfo。"""
        prompt_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
        completion_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
        total_tokens = getattr(usage, "total_tokens", None) if usage else None
        return UsageInfo(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens if total_tokens is not None else prompt_tokens + completion_tokens,
        )

    async def chat_completion(self, request: ChatRequest) -> ChatResponse:
        """调用 DeepSeek 非流式聊天补全接口并返回统一响应。"""
        start_time = time.time()
        response = await self.client.chat.completions.create(
            model=self.model_name,
            messages=self._build_messages(request),
            stream=False,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            response_format=request.response_format,
        )
        message = response.choices[0].message

        return ChatResponse(
            id=response.id,
            model=response.model,
            content=message.content or "",
            usage=self._build_usage(response.usage),
            reasoning=getattr(message, "reasoning_content", None),
            latency_ms=(time.time() - start_time) * 1000,
            first_token_latency_ms=None,
        )

    async def chat_completion_stream(self, request: ChatRequest) -> AsyncGenerator[Dict[str, Any], None]:
        """调用 DeepSeek 流式接口，并将内容和推理片段转换为网关事件。"""
        stream = await self.client.chat.completions.create(
            model=self.model_name,
            messages=self._build_messages(request),
            stream=True,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            response_format=request.response_format,
        )

        async for chunk in stream:
            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                yield {"type": "reasoning", "content": reasoning}

            if delta.content:
                yield {"type": "content", "content": delta.content}
