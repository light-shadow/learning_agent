"""FastAPI 应用工厂与本地启动入口。"""
from __future__ import annotations

from fastapi import FastAPI

from app.api import router as agent_router
from app.internal_handler import router as internal_router
from app.runtime import AgentRuntime, RuleBasedPlanner
from app.ticket_store import InMemoryTicketStore
from app.tools import ToolRegistry, register_default_tools


def create_app() -> FastAPI:
    """创建包含离线 Agent Runtime 和假内部工单 handler 的应用实例。"""
    app = FastAPI(
        title="Offline Agent Runtime",
        version="0.1.0",
        description="不调用模型 API、不访问真实网络的 Agent Runtime 骨架。",
    )
    app.state.ticket_store = InMemoryTicketStore()
    app.include_router(internal_router)

    tool_registry = ToolRegistry()
    register_default_tools(tool_registry, app)
    app.state.agent_runtime = AgentRuntime(RuleBasedPlanner(), tool_registry)
    app.include_router(agent_router)
    return app


app = create_app()
