# adapters/openai_adapter.py
import time
import json
from typing import AsyncGenerator, Dict, Any
from openai import AsyncOpenAI
from models import ChatRequest, ChatResponse, UsageInfo
from adapters.base import BaseAdapter
from config import OPENAI_API_KEY

class OpenAIAdapter(BaseAdapter):
    def __init__(self, model_name: str, api_key: str = OPENAI_API_KEY):
        super().__init__(model_name, api_key)
        self.client = AsyncOpenAI(api_key=api_key)

    async def chat_completion(self, request: ChatRequest) -> ChatResponse:
        start_time = time.time()
        first_token_time = None
        # 转换消息格式
        messages = [msg.dict() for msg in request.messages]
        # 如果请求包含 response_format，则按 OpenAI 格式处理
        response_format = request.response_format
        if response_format:
            if response_format.get("type") == "json_object":
                response_format = {"type": "json_object"}
            else:
                # 如果是 json_schema，需要构造 schema
                pass

        # 使用 responses API（此处用 chat.completions 模拟，因为 responses 仍为beta）
        # 这里为了演示，实际使用 chat.completions 并添加 response_format
        response = await self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            stream=False,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            response_format=response_format,
        )

        content = response.choices[0].message.content
        usage = response.usage
        total_time = (time.time() - start_time) * 1000  # ms

        return ChatResponse(
            id=response.id,
            model=response.model,
            content=content,
            usage=UsageInfo(
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
            ),
            latency_ms=total_time,
            first_token_latency_ms=None,  # 非流式无首token
            reasoning=None,
        )

    async def chat_completion_stream(self, request: ChatRequest) -> AsyncGenerator[Dict[str, Any], None]:
        messages = [msg.dict() for msg in request.messages]
        response_format = request.response_format
        if response_format and response_format.get("type") == "json_object":
            response_format = {"type": "json_object"}
        else:
            response_format = None

        start_time = time.time()
        first_token_sent = False

        stream = await self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            stream=True,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            response_format=response_format,
        )

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                if not first_token_sent:
                    first_token_time = (time.time() - start_time) * 1000
                    first_token_sent = True
                # 发送文本片段
                yield {
                    "type": "content",
                    "content": content,
                }
            # 注意：OpenAI 流式 chunk 不包含 usage，需自行计算或从最后获取

        # 流结束后，可以发送结束事件（包含 usage）
        # 由于无法从流中获取 usage，这里不提供，可后续改进