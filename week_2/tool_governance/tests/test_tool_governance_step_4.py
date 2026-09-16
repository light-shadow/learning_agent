"""第 4 轮完整离线治理验收测试。"""

from dataclasses import asdict, replace
import json

import pytest

from tool_governance_demo_step_4 import ToolCall, build_demo_environment, make_context


@pytest.fixture()
def environment():
    """为每项断言创建隔离的真实 Runtime 环境。"""

    return build_demo_environment()


def refund(amount: int = 100, call_id: str = "refund-1") -> ToolCall:
    """构造不携带任何服务端字段的退款调用。"""

    return ToolCall(call_id, "create_refund", {"order_id": "ORD-1001", "amount": amount, "reason": "客户退款"})


def approve(environment, call: ToolCall, context) -> str:
    """模拟可信审批界面按规范参数签发审批。"""

    return environment.approvals.issue(context, call.name, environment.runtime.validate_arguments(call).model_dump(mode="json"))


def test_deny_first_bypass_has_no_shell_side_effect(environment) -> None:
    """验证硬拒绝发生在 bypass 之前且 handler 为零调用。"""

    result = environment.runtime.invoke(ToolCall("shell", "run_shell", {"command": "rm -rf /"}), make_context("bypassPermissions"))
    assert (result.decision, result.code, environment.services.shell_executions) == ("deny", "DENY_RULE", 0)


def test_plan_rejects_write_before_approval(environment) -> None:
    """验证 plan 在审批以前拒绝写操作。"""

    result = environment.runtime.invoke(refund(), make_context("plan"))
    assert (result.code, environment.services.refund_executions) == ("PLAN_READ_ONLY", 0)


@pytest.mark.parametrize("field,value", [("user_id", "admin"), ("approved", True), ("approval_id", "forged")])
def test_schema_rejects_server_control_fields(environment, field: str, value: object) -> None:
    """验证模型不能伪造身份、确认或审批。"""

    call = refund(); arguments = dict(call.arguments); arguments[field] = value
    result = environment.runtime.invoke(replace(call, arguments=arguments), make_context())
    assert (result.code, environment.services.refund_executions) == ("INVALID_ARGUMENTS", 0)


def test_rbac_denial_calls_no_handler(environment) -> None:
    """验证权限不足时退款 handler 零调用。"""

    result = environment.runtime.invoke(refund(), make_context(permissions=frozenset({"order:read"})))
    assert (result.code, environment.services.refund_executions) == ("PERMISSION_DENIED", 0)


def test_changed_approval_arguments_require_new_confirmation(environment) -> None:
    """验证批准 100 元后改成 399 元会失效。"""

    context, original = make_context(), refund(100)
    approval_id = approve(environment, original, context)
    result = environment.runtime.invoke(refund(399, "changed"), replace(context, approval_id=approval_id))
    assert (result.decision, result.code, environment.services.refund_executions) == ("confirm", "APPROVAL_REQUIRED", 0)


def test_redaction_and_minimal_audit_boundary(environment) -> None:
    """验证敏感结果已脱敏，审计保留 ID 但不保留敏感值。"""

    result = environment.runtime.invoke(ToolCall("query", "get_order", {"order_id": "ORD-1001"}), make_context())
    audit = json.dumps([asdict(item) for item in environment.audit.records], ensure_ascii=False)
    assert result.content["customer_email"] == "c***@example.com"
    assert result.content["access_token"] == "[REDACTED]"
    assert "query" in audit and "customer@example.com" not in audit and "demo-access-token" not in audit


def test_discovery_and_execution_both_enforce_allowlist(environment) -> None:
    """验证模型不可见且旧 Tool Call 在执行期仍被拒绝。"""

    context = make_context(allowed_tools=frozenset({"get_order"}))
    visible = {item["function"]["name"] for item in environment.runtime.discover(context)}
    result = environment.runtime.invoke(refund(), context)
    assert visible == {"get_order"}
    assert (result.code, environment.services.refund_executions) == ("TOOL_NOT_ALLOWED", 0)


def test_one_time_approval_prevents_replay(environment) -> None:
    """验证审批只允许第一笔执行，重放不会增加退款副作用。"""

    context, call = make_context(), refund()
    approved_context = replace(context, approval_id=approve(environment, call, context))
    first = environment.runtime.invoke(call, approved_context)
    second = environment.runtime.invoke(replace(call, tool_call_id="replay"), approved_context)
    assert first.success is True
    assert (second.decision, second.code, environment.services.refund_executions) == ("confirm", "APPROVAL_REQUIRED", 1)
