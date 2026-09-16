"""第 2 轮：在第 1 轮对象模型上加入固定顺序的 PermissionEngine。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Literal

from pydantic import BaseModel

from tool_governance_demo_step_1 import (
    CreateRefundArguments,
    DecisionState,
    RunShellArguments,
    ToolPolicy,
)


PermissionMode = Literal["default", "plan", "bypassPermissions"]
Precheck = Callable[[BaseModel, "ExecutionContext"], "Decision | None"]


@dataclass(frozen=True)
class ExecutionContext:
    """保存可信服务端提供的身份、权限与本轮白名单。"""

    trace_id: str
    user_id: str
    tenant_id: str
    permissions: frozenset[str]
    allowed_tools: frozenset[str]
    permission_mode: PermissionMode = "default"


@dataclass(frozen=True)
class Decision:
    """描述权限引擎的三态结果及稳定原因码。"""

    state: DecisionState
    code: str
    reason: str
    source: str


@dataclass(frozen=True)
class ToolDefinition:
    """第 2 轮仅保存权限判定所需的工具元数据。"""

    name: str
    argument_model: type[BaseModel]
    policy: ToolPolicy
    precheck: Precheck


class PermissionEngine:
    """按 deny、plan、白名单、RBAC、业务前检的固定顺序作出决策。"""

    _HARD_SHELL_DENY = re.compile(r"(?:\brm\s+-rf\b|\bmkfs\b|\bshutdown\b)", re.IGNORECASE)

    def decide(self, definition: ToolDefinition, arguments: BaseModel, context: ExecutionContext) -> Decision:
        """执行第 2 轮可验证的拒绝路径；本方法绝不调用 handler。"""

        command = str(getattr(arguments, "command", ""))
        # 1. 硬拒绝永远优先，bypass 也不能跨过该边界。
        if definition.policy.effect == "shell" and self._HARD_SHELL_DENY.search(command):
            return Decision("deny", "DENY_RULE", "命令命中硬拒绝规则", "deny_rule")
        # 2. 计划模式由执行层强制为只读。
        if context.permission_mode == "plan" and definition.policy.effect != "read":
            return Decision("deny", "PLAN_READ_ONLY", "plan 模式只允许只读工具", "plan")
        # 3. 即便模型曾看见工具，也必须在执行期重验白名单。
        if definition.name not in context.allowed_tools:
            return Decision("deny", "TOOL_NOT_ALLOWED", "本轮不允许该工具", "allowed_tools")
        # 4. RBAC。
        if definition.policy.permission not in context.permissions:
            return Decision("deny", "PERMISSION_DENIED", "当前身份缺少工具权限", "rbac")
        # 5. 业务预检查。
        result = definition.precheck(arguments, context)
        if result is not None:
            return result
        # 第 2 轮还没有审批存储；高风险工具先明确要求确认。
        if definition.policy.risk == "high" or definition.policy.requires_approval:
            return Decision("confirm", "APPROVAL_REQUIRED", "需要人工审批", "approval")
        return Decision("allow", "ALLOWED", "治理检查通过", "default")


def no_precheck(arguments: BaseModel, context: ExecutionContext) -> Decision | None:
    """表示该教学示例无额外业务前置检查。"""

    del arguments, context
    return None


def demo_context(mode: PermissionMode = "default") -> ExecutionContext:
    """构造仅供离线演示使用的可信上下文。"""

    return ExecutionContext("trace-step2", "user-1", "tenant-a", frozenset({"refund:create", "shell:run"}), frozenset({"create_refund", "run_shell"}), mode)


def main() -> None:
    """演示 hard deny 与 plan 的拒绝顺序。"""

    engine = PermissionEngine()
    shell = ToolDefinition("run_shell", RunShellArguments, ToolPolicy("shell", "medium", "shell:run", False, 1, 0, False), no_precheck)
    refund = ToolDefinition("create_refund", CreateRefundArguments, ToolPolicy("write", "high", "refund:create", True, 1, 0, False), no_precheck)
    print(engine.decide(shell, RunShellArguments(command="rm -rf /"), demo_context("bypassPermissions")))
    print(engine.decide(refund, CreateRefundArguments(order_id="ORD-1001", amount=100, reason="客户退款"), demo_context("plan")))


if __name__ == "__main__":
    main()
