"""对外暴露 Agent Runtime 的 API 路由。"""
from __future__ import annotations

from fastapi import APIRouter, Request

from app.runtime import AgentRuntime
from app.schemas import AgentRunRequest, AgentRunResponse

router = APIRouter(prefix="/v1/agent", tags=["agent"])


def _get_runtime(request: Request) -> AgentRuntime:
    """从应用状态中取得已初始化的 Agent Runtime。"""
    return request.app.state.agent_runtime


@router.post("/runs", response_model=AgentRunResponse)
async def run_agent(request_body: AgentRunRequest, request: Request) -> AgentRunResponse:
    """接收用户问题并执行一次完全离线的 Agent 运行。"""
    return await _get_runtime(request).run(request_body)
