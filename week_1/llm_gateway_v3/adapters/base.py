"""供应商适配器抽象接口。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from config import ModelConfig
from models import InternalRequest, Usage


class BaseAdapter(ABC):
    """定义所有供应商适配器必须实现的统一调用协议。"""

    @abstractmethod
    async def complete(self, config: ModelConfig, request: InternalRequest) -> tuple[str, Usage, str | None]:
        """执行非流式调用并返回内容、用量和可选推理文本。"""

    @abstractmethod
    async def stream(self, config: ModelConfig, request: InternalRequest) -> AsyncIterator[dict[str, str]]:
        """执行流式调用并逐项产出 content 或 reasoning 事件。"""
