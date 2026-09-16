"""第 2 轮的拒绝路径测试。"""

from tool_governance_demo_step_1 import RunShellArguments, ToolPolicy
from tool_governance_demo_step_2 import PermissionEngine, ToolDefinition, demo_context, no_precheck


def test_bypass_cannot_cross_hard_deny() -> None:
    """验证 bypass 仍无法覆盖第一顺位硬拒绝。"""

    definition = ToolDefinition("run_shell", RunShellArguments, ToolPolicy("shell", "medium", "shell:run", False, 1, 0, False), no_precheck)
    decision = PermissionEngine().decide(definition, RunShellArguments(command="rm -rf /"), demo_context("bypassPermissions"))
    assert decision.code == "DENY_RULE"

