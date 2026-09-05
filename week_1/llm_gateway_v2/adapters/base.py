# adapters/base.py
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Dict, Any, Optional
from models import ChatRequest, ChatResponse, UsageInfo

class BaseAdapter(ABC):
    """所有适配器的抽象基类"""

    def __init__(self, model_name: str, api_key: str):
        self.model_name = model_name
        self.api_key = api_key

    @abstractmethod
    async def chat_completion(self, request: ChatRequest) -> ChatResponse:
        """非流式调用，返回完整响应"""
        pass

    @abstractmethod
    async def chat_completion_stream(self, request: ChatRequest) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式调用，产生 SSE 格式的片段。
        每个片段为字典，包含 type, content, usage, reasoning 等。
        """
        pass