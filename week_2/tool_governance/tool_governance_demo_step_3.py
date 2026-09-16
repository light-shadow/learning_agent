"""第 3 轮：组装唯一 ToolRuntime 与离线调用骨架，尚未引入审批和审计。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from pydantic import BaseModel, ValidationError

from tool_governance_demo_step_1 import (
    CreateRefundArguments,
    GetOrderArguments,
    RunShellArguments,
    ToolCall,
    ToolPolicy,
    ToolResult,
)
from tool_governance_demo_step_2 import Decision, ExecutionContext, PermissionEngine, ToolDefinition, no_precheck


Handler = Callable[[BaseModel, ExecutionContext], Mapping[str, Any]]


@dataclass(frozen=True)
class RuntimeToolDefinition:
    """在权限元数据上附加仅 Runtime 持有的 handler 和模型描述。"""

    definition: ToolDefinition
    description: str
    handler: Handler


class ToolRuntime:
    """提供离线调用、未来 CLI 与 Provider 共同使用的唯一入口。"""

    def __init__(self, definitions: Sequence[RuntimeToolDefinition], engine: PermissionEngine) -> None:
        """注册名称唯一的工具定义和确定性权限引擎。"""

        self._definitions = {item.definition.name: item for item in definitions}
        if len(self._definitions) != len(definitions):
            raise ValueError("工具名称必须唯一")
        self._engine = engine

    def discover(self, context: ExecutionContext) -> list[dict[str, Any]]:
        """仅向模型投影白名单内工具的名称、描述与 Pydantic Schema。"""

        return [
            {"type": "function", "function": {"name": item.definition.name, "description": item.description, "parameters": item.definition.argument_model.model_json_schema()}}
            for name, item in sorted(self._definitions.items())
            if name in context.allowed_tools
        ]

    def invoke(self, call: ToolCall, context: ExecutionContext) -> ToolResult:
        """执行查找、参数校验、三态决策和 allow 后 handler 调用。"""

        item = self._definitions.get(call.name)
        if item is None:
            return ToolResult(call.tool_call_id, call.name, False, "deny", "TOOL_NOT_FOUND", {"message": "工具不存在"}, False)
        try:
            arguments = item.definition.argument_model.model_validate(call.arguments)
        except ValidationError:
            return ToolResult(call.tool_call_id, call.name, False, "deny", "INVALID_ARGUMENTS", {"message": "参数不符合 Schema"}, False)
        decision = self._engine.decide(item.definition, arguments, context)
        if decision.state != "allow":
            return ToolResult(call.tool_call_id, call.name, False, decision.state, decision.code, {"message": decision.reason}, False)
        try:
            content = dict(item.handler(arguments, context))
        except Exception:
            return ToolResult(call.tool_call_id, call.name, False, "allow", "HANDLER_ERROR", {"message": "工具执行失败"}, False)
        return ToolResult(call.tool_call_id, call.name, True, "allow", "OK", content, False)


@dataclass
class OfflineServices:
    """保存离线教学所需的内存订单与副作用计数。"""

    refund_executions: int = 0
    shell_executions: int = 0


def build_runtime() -> tuple[ToolRuntime, OfflineServices]:
    """组装第 3 轮离线 Runtime；所有工具均通过 invoke 进入 handler。"""

    services = OfflineServices()
    engine = PermissionEngine()

    def get_order(arguments: BaseModel, context: ExecutionContext) -> Mapping[str, Any]:
        """返回内存订单，下一轮会在 finalize 阶段进行脱敏。"""

        del context
        typed = arguments if isinstance(arguments, GetOrderArguments) else None
        if typed is None:
            raise TypeError("参数类型错误")
        return {"order_id": typed.order_id, "status": "PAID", "customer_email": "customer@example.com", "access_token": "demo-token"}

    def create_refund(arguments: BaseModel, context: ExecutionContext) -> Mapping[str, Any]:
        """模拟退款副作用；第 3 轮仍会因高风险决策停在 confirm。"""

        del context
        typed = arguments if isinstance(arguments, CreateRefundArguments) else None
        if typed is None:
            raise TypeError("参数类型错误")
        services.refund_executions += 1
        return {"refund_id": f"REF-{services.refund_executions}", "amount": typed.amount}

    def run_shell(arguments: BaseModel, context: ExecutionContext) -> Mapping[str, Any]:
        """只增加计数，明确不启动真实子进程。"""

        del context
        typed = arguments if isinstance(arguments, RunShellArguments) else None
        if typed is None:
            raise TypeError("参数类型错误")
        services.shell_executions += 1
        return {"command": typed.command, "status": "SIMULATED"}

    definitions = [
        RuntimeToolDefinition(ToolDefinition("get_order", GetOrderArguments, ToolPolicy("read", "low", "order:read", False, 1, 1, True), no_precheck), "查询订单", get_order),
        RuntimeToolDefinition(ToolDefinition("create_refund", CreateRefundArguments, ToolPolicy("write", "high", "refund:create", True, 1, 0, False), no_precheck), "创建退款", create_refund),
        RuntimeToolDefinition(ToolDefinition("run_shell", RunShellArguments, ToolPolicy("shell", "medium", "shell:run", False, 1, 0, False), no_precheck), "模拟 Shell", run_shell),
    ]
    return ToolRuntime(definitions, engine), services


def demo_context() -> ExecutionContext:
    """构造包含完整权限的离线可信上下文。"""

    return ExecutionContext("trace-step3", "user-1", "tenant-a", frozenset({"order:read", "refund:create", "shell:run"}), frozenset({"get_order", "create_refund", "run_shell"}))


def main() -> None:
    """运行一次查询与一次未审批退款，展示唯一入口的三态行为。"""

    runtime, services = build_runtime()
    context = demo_context()
    print(runtime.invoke(ToolCall("query-1", "get_order", {"order_id": "ORD-1001"}), context).to_json())
    print(runtime.invoke(ToolCall("refund-1", "create_refund", {"order_id": "ORD-1001", "amount": 100, "reason": "客户退款"}), context).to_json())
    print(f"refund_executions={services.refund_executions}, shell_executions={services.shell_executions}")


if __name__ == "__main__":
    main()
