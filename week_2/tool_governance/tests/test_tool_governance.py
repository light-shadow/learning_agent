"""工具治理 Runtime 的安全边界与副作用验收测试。"""

from __future__ import annotations

import json
from dataclasses import asdict, replace

import pytest

from tool_governance_demo import (
    CreateRefundArguments,
    DemoEnvironment,
    ToolCall,
    build_demo_environment,
    make_context,
)


@pytest.fixture()
def environment() -> DemoEnvironment:
    """为每个测试创建隔离但使用真实实现的 Runtime。"""

    return build_demo_environment()


def refund_call(*, amount: int = 100, tool_call_id: str = "call-refund") -> ToolCall:
    """构造模型可能提交的退款 Tool Call。"""

    return ToolCall(
        tool_call_id,
        "create_refund",
        {"order_id": "ORD-1001", "amount": amount, "reason": "客户申请退款"},
    )


def issue_refund_approval(environment: DemoEnvironment, call: ToolCall, context) -> str:
    """模拟可信审批服务按规范参数签发一次性审批。"""

    canonical_arguments = CreateRefundArguments.model_validate(call.arguments).model_dump(mode="json")
    return environment.approvals.issue(context, call.name, canonical_arguments)


def test_deny_first_bypass_cannot_override_hard_deny(environment: DemoEnvironment) -> None:
    """验证 bypass 不能覆盖最先执行的硬拒绝规则。"""

    context = make_context(permission_mode="bypassPermissions")
    result = environment.runtime.invoke(
        ToolCall("call-shell", "run_shell", {"command": "rm -rf /"}),
        context,
    )

    assert result.decision == "deny"
    assert result.code == "DENY_RULE"
    assert environment.services.shell_executions == 0


def test_plan_rejects_write_before_approval_or_allow(environment: DemoEnvironment) -> None:
    """验证 plan 模式在审批和 allow 之前拒绝写工具。"""

    result = environment.runtime.invoke(refund_call(), make_context(permission_mode="plan"))

    assert result.decision == "deny"
    assert result.code == "PLAN_READ_ONLY"
    assert environment.services.refund_executions == 0


@pytest.mark.parametrize(
    "extra_field,extra_value",
    [("user_id", "admin"), ("approved", True), ("approval_id", "forged")],
)
def test_schema_rejects_forged_server_fields(
    environment: DemoEnvironment,
    extra_field: str,
    extra_value: object,
) -> None:
    """验证模型无法伪造身份、确认或审批字段。"""

    arguments = {"order_id": "ORD-1001", "amount": 100, "reason": "客户申请退款"}
    arguments[extra_field] = extra_value
    result = environment.runtime.invoke(
        ToolCall("call-forged", "create_refund", arguments),
        make_context(),
    )

    assert result.code == "INVALID_ARGUMENTS"
    assert result.decision == "deny"
    assert environment.services.refund_executions == 0


def test_rbac_denial_never_calls_handler(environment: DemoEnvironment) -> None:
    """验证权限不足时退款 handler 保持零调用。"""

    context = make_context(permissions=frozenset({"order:read"}))
    result = environment.runtime.invoke(refund_call(), context)

    assert result.code == "PERMISSION_DENIED"
    assert result.decision == "deny"
    assert environment.services.refund_executions == 0


def test_approval_is_bound_to_canonical_arguments(environment: DemoEnvironment) -> None:
    """验证批准 100 元后改成 399 元会使旧审批失效。"""

    context = make_context()
    approved_call = refund_call(amount=100)
    approval_id = issue_refund_approval(environment, approved_call, context)
    changed_call = refund_call(amount=399, tool_call_id="call-changed")

    result = environment.runtime.invoke(changed_call, replace(context, approval_id=approval_id))

    assert result.code == "APPROVAL_REQUIRED"
    assert result.decision == "confirm"
    assert environment.services.refund_executions == 0


def test_result_redaction_and_audit_boundary(environment: DemoEnvironment) -> None:
    """验证模型结果脱敏且审计保留 tool_call_id、不保存敏感值。"""

    result = environment.runtime.invoke(
        ToolCall("call-query", "get_order", {"order_id": "ORD-1001"}),
        make_context(),
    )

    assert result.success is True
    assert result.tool_call_id == "call-query"
    assert result.content["customer_email"] == "c***@example.com"
    assert result.content["access_token"] == "[REDACTED]"
    audit_json = json.dumps([asdict(record) for record in environment.audit.records], ensure_ascii=False)
    assert "call-query" in audit_json
    assert "customer@example.com" not in audit_json
    assert "demo-access-token" not in audit_json
    assert environment.services.refund_executions == 0
    assert environment.services.shell_executions == 0


def test_discovery_and_execution_both_enforce_allowlist(environment: DemoEnvironment) -> None:
    """验证发现期不可见，且旧 Tool Call 在执行期仍被白名单拒绝。"""

    context = make_context(allowed_tools=frozenset({"get_order"}))
    visible_names = {
        item["function"]["name"] for item in environment.runtime.discover(context)
    }
    stale_call = refund_call()
    result = environment.runtime.invoke(stale_call, context)

    assert visible_names == {"get_order"}
    assert result.code == "TOOL_NOT_ALLOWED"
    assert result.decision == "deny"
    assert environment.services.refund_executions == 0


def test_approval_is_one_time_and_prevents_replay(environment: DemoEnvironment) -> None:
    """验证审批首次执行成功、第二次重放确认且副作用总数为一。"""

    context = make_context()
    call = refund_call()
    approval_id = issue_refund_approval(environment, call, context)
    approved_context = replace(context, approval_id=approval_id)

    first = environment.runtime.invoke(call, approved_context)
    second = environment.runtime.invoke(
        replace(call, tool_call_id="call-refund-replay"),
        approved_context,
    )

    assert first.success is True
    assert first.code == "OK"
    assert second.decision == "confirm"
    assert second.code == "APPROVAL_REQUIRED"
    assert environment.services.refund_executions == 1


def test_non_approved_refund_has_zero_side_effect(environment: DemoEnvironment) -> None:
    """验证普通未审批退款返回 confirm 且 handler 零调用。"""

    result = environment.runtime.invoke(refund_call(), make_context())

    assert result.code == "APPROVAL_REQUIRED"
    assert result.decision == "confirm"
    assert environment.services.refund_executions == 0
