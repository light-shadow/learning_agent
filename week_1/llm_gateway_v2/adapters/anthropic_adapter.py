# adapters/anthropic_adapter.py
import time
import json
from typing import AsyncGenerator, Dict, Any
from anthropic import AsyncAnthropic
from models import ChatRequest, ChatResponse, UsageInfo
from adapters.base import BaseAdapter
from config import ANTHROPIC_API_KEY

class AnthropicAdapter(BaseAdapter):
    def __init__(self, model_name: str, api_key: str = ANTHROPIC_API_KEY):
        super().__init__(model_name, api_key)
        self.client = AsyncAnthropic(api_key=api_key)

    async def chat_completion(self, request: ChatRequest) -> ChatResponse:
        start_time = time.time()
        # 转换消息：Anthropic 要求系统消息单独提取
        system = None
        messages = []
        for msg in request.messages:
            if msg.role == "system":
                system = msg.content
            else:
                messages.append({"role": msg.role, "content": msg.content})

        # 结构化输出：Anthropic 不支持原生 response_format，可以用 tool 模拟
        # 此处简化，仅当 response_format 要求 json 时在提示中强调
        if request.response_format and request.response_format.get("type") == "json_object":
            # 在最后一条消息中附加要求
            if messages and messages[-1]["role"] == "user":
                messages[-1]["content"] += "\n\n你必须以合法的JSON格式输出。不要包含任何额外文本。"

        response = await self.client.messages.create(
            model=self.model_name,
            system=system,
            messages=messages,
            stream=False,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )

        content = response.content[0].text
        usage = response.usage
        total_time = (time.time() - start_time) * 1000

        return ChatResponse(
            id=response.id,
            model=response.model,
            content=content,
            usage=UsageInfo(
                prompt_tokens=usage.input_tokens,
                completion_tokens=usage.output_tokens,
                total_tokens=usage.input_tokens + usage.output_tokens,
            ),
            latency_ms=total_time,
            first_token_latency_ms=None,
            reasoning=None,
        )

    async def chat_completion_stream(self, request: ChatRequest) -> AsyncGenerator[Dict[str, Any], None]:
        system = None
        messages = []
        for msg in request.messages:
            if msg.role == "system":
                system = msg.content
            else:
                messages.append({"role": msg.role, "content": msg.content})

        if request.response_format and request.response_format.get("type") == "json_object":
            if messages and messages[-1]["role"] == "user":
                messages[-1]["content"] += "\n\n你必须以合法的JSON格式输出。不要包含任何额外文本。"

        start_time = time.time()
        first_token_sent = False

        async with self.client.messages.stream(
            model=self.model_name,
            system=system,
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        ) as stream:
            async for event in stream:
                if event.type == "text":
                    content = event.text
                    if not first_token_sent:
                        first_token_time = (time.time() - start_time) * 1000
                        first_token_sent = True
                    yield {
                        "type": "content",
                        "content": content,
                    }
                # 其他事件如 message_stop 等，可忽略