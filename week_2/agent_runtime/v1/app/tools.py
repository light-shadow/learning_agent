"""Agent 工具定义、注册和进程内 HTTP 调用适配器。"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from fastapi import FastAPI

from app.schemas import CreateTicketInput, Ticket

ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class ToolRegistry:
    """保存名称到工具处理函数的映射，并统一执行入口。"""

    def __init__(self) -> None:
        """初始化空的工具注册表。"""
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, tool_name: str, handler: ToolHandler) -> None:
        """注册一个工具；重复名称会被拒绝以避免运行时误调用。"""
        if tool_name in self._handlers:
            raise ValueError(f"工具已注册: {tool_name}")
        self._handlers[tool_name] = handler

    async def invoke(self, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        """按名称执行已注册的工具并返回 JSON 兼容结果。"""
        handler = self._handlers.get(tool_name)
        if handler is None:
            raise ValueError(f"未注册的工具: {tool_name}")
        return await handler(tool_input)


class InProcessCreateTicketClient:
    """通过 ASGITransport 调用假内部 handler，不建立真实网络连接。"""

    def __init__(self, app: FastAPI) -> None:
        """保存当前应用实例，作为进程内 HTTP 调用的目标。"""
        self._app = app

    async def create_ticket(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        """向进程内 create_ticket handler 提交请求并校验返回契约。"""
        validated_input = CreateTicketInput.model_validate(tool_input)
        transport = httpx.ASGITransport(app=self._app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://agent-runtime.internal",
        ) as client:
            response = await client.post(
                "/internal/tools/create_ticket",
                json=validated_input.model_dump(mode="json"),
            )
        response.raise_for_status()
        ticket = Ticket.model_validate(response.json())
        return ticket.model_dump(mode="json")


def register_default_tools(registry: ToolRegistry, app: FastAPI) -> None:
    """注册本示例默认的 create_ticket 工具及其进程内 HTTP 适配器。"""
    client = InProcessCreateTicketClient(app)
    registry.register("create_ticket", client.create_ticket)
