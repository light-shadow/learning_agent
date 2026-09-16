"""不依赖模型 API 的确定性 Agent Runtime 骨架。"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from app.schemas import AgentRunRequest, AgentRunResponse, CreateTicketInput, TicketPriority, ToolCallResult
from app.tools import ToolRegistry


@dataclass(frozen=True)
class PlannedToolCall:
    """规则规划器生成的一次待执行工具调用。"""

    tool_name: str
    tool_input: dict[str, object]


class RuleBasedPlanner:
    """用确定性规则替代 LLM，专注验证 Runtime 的规划与工具编排链路。"""

    def plan(self, request: AgentRunRequest) -> PlannedToolCall:
        """将用户问题转换为 create_ticket 工具调用参数。"""
        message = request.message.strip()
        ticket_input = CreateTicketInput(
            reporter_id=request.user_id,
            title=self._build_title(message),
            description=message,
            category=self._choose_category(message),
            priority=self._choose_priority(message),
        )
        return PlannedToolCall(
            tool_name="create_ticket",
            tool_input=ticket_input.model_dump(mode="json"),
        )

    def _build_title(self, message: str) -> str:
        """从用户描述提取可读且不超过接口上限的工单标题。"""
        compact_message = " ".join(message.split())
        return compact_message[:80]

    def _choose_category(self, message: str) -> str:
        """依据常见餐饮服务问题关键字确定一个稳定的工单分类。"""
        if any(keyword in message for keyword in ("支付", "退款", "扣款", "优惠券")):
            return "payment"
        if any(keyword in message for keyword in ("订单", "配送", "漏送", "取餐")):
            return "order"
        if any(keyword in message for keyword in ("咖啡", "饮品", "食品", "口味", "质量")):
            return "product"
        return "service"

    def _choose_priority(self, message: str) -> TicketPriority:
        """依据紧急关键字给出简单、可预测的优先级。"""
        if any(keyword in message for keyword in ("食品安全", "过敏", "人身", "紧急")):
            return TicketPriority.URGENT
        if any(keyword in message for keyword in ("无法", "严重", "多次", "一直")):
            return TicketPriority.HIGH
        return TicketPriority.NORMAL


class AgentRuntime:
    """串联规划、工具执行和结果汇总的最小 Runtime。"""

    def __init__(self, planner: RuleBasedPlanner, tool_registry: ToolRegistry) -> None:
        """注入规划器与工具注册表，便于后续替换成真实实现。"""
        self._planner = planner
        self._tool_registry = tool_registry

    async def run(self, request: AgentRunRequest) -> AgentRunResponse:
        """执行一次离线 Agent 任务，并记录工具调用成功或失败结果。"""
        run_id = f"run_{uuid4().hex}"
        planned_call = self._planner.plan(request)
        try:
            tool_output = await self._tool_registry.invoke(planned_call.tool_name, planned_call.tool_input)
        except Exception as exc:
            tool_call = ToolCallResult(
                tool_name=planned_call.tool_name,
                input=planned_call.tool_input,
                status="failed",
                error=str(exc),
            )
            return AgentRunResponse(
                run_id=run_id,
                status="failed",
                output="工单创建失败，请稍后重试。",
                tool_calls=[tool_call],
            )

        tool_call = ToolCallResult(
            tool_name=planned_call.tool_name,
            input=planned_call.tool_input,
            status="success",
            output=tool_output,
        )
        return AgentRunResponse(
            run_id=run_id,
            status="completed",
            output=f"已创建工单 {tool_output['ticket_id']}，当前状态为 {tool_output['status']}。",
            tool_calls=[tool_call],
        )
