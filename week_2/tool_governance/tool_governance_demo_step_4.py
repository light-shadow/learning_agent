"""第 4 轮：加入审批、超时恢复、脱敏、审计及完整离线测试所需的 Runtime。"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Callable, Literal, Mapping, Sequence
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from tool_governance_demo_step_1 import (
    CreateRefundArguments, DecisionState, GetOrderArguments, RunShellArguments,
    ToolCall, ToolPolicy, ToolResult,
)


PermissionMode = Literal["default", "plan", "bypassPermissions"]
Handler = Callable[[BaseModel, "ExecutionContext"], Mapping[str, Any]]
Precheck = Callable[[BaseModel, "ExecutionContext"], "Decision | None"]


@dataclass(frozen=True)
class ExecutionContext:
    """保存服务端可信身份、租户、白名单、模式和已签发审批 ID。"""

    trace_id: str
    user_id: str
    tenant_id: str
    permissions: frozenset[str]
    allowed_tools: frozenset[str]
    permission_mode: PermissionMode = "default"
    approval_id: str | None = None


@dataclass(frozen=True)
class Decision:
    """描述无副作用的 allow、deny 或 confirm 决策。"""

    state: DecisionState
    code: str
    reason: str
    source: str


@dataclass(frozen=True)
class ToolDefinition:
    """聚合仅 Runtime 可访问的工具实现和治理元数据。"""

    name: str
    description: str
    argument_model: type[BaseModel]
    policy: ToolPolicy
    handler: Handler
    precheck: Precheck
    result_fields: tuple[str, ...]


def arguments_digest(arguments: Mapping[str, Any]) -> str:
    """将递归排序的稳定 JSON 参数计算为审批绑定摘要。"""

    encoded = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass
class ApprovalRecord:
    """保存一次性、带租户和参数绑定的审批记录。"""

    user_id: str
    tenant_id: str
    tool_name: str
    arguments_sha256: str
    expires_at: float
    used: bool = False


class ApprovalStore:
    """签发并原子消费审批；不存在的 ID 也按未审批处理。"""

    def __init__(self) -> None:
        """初始化内存审批表和并发锁。"""

        self._records: dict[str, ApprovalRecord] = {}
        self._lock = threading.Lock()

    def issue(self, context: ExecutionContext, tool_name: str, arguments: Mapping[str, Any], ttl_seconds: float = 300) -> str:
        """为已展示给人工的规范参数签发一次性审批。"""

        approval_id = f"apr_{uuid4().hex}"
        with self._lock:
            self._records[approval_id] = ApprovalRecord(context.user_id, context.tenant_id, tool_name, arguments_digest(arguments), time.time() + ttl_seconds)
        return approval_id

    def consume(self, approval_id: str | None, context: ExecutionContext, tool_name: str, arguments: Mapping[str, Any]) -> bool:
        """校验身份、租户、工具、参数和过期状态后一次性消费审批。"""

        if not approval_id:
            return False
        with self._lock:
            record = self._records.get(approval_id)
            if record is None or record.used or record.expires_at <= time.time():
                return False
            if (record.user_id, record.tenant_id, record.tool_name, record.arguments_sha256) != (context.user_id, context.tenant_id, tool_name, arguments_digest(arguments)):
                return False
            record.used = True
            return True


@dataclass(frozen=True)
class AuditRecord:
    """保存最小审计信息，永不记录参数值、Token 或 traceback。"""

    trace_id: str
    tool_call_id: str
    tool_name: str
    user_id: str
    tenant_id: str
    phase: Literal["decision", "execution"]
    status: str
    code: str
    argument_keys: tuple[str, ...]
    latency_ms: int


class AuditSink:
    """线程安全保存最小化审计事件。"""

    def __init__(self) -> None:
        """初始化审计事件列表。"""

        self._records: list[AuditRecord] = []
        self._lock = threading.Lock()

    @property
    def records(self) -> tuple[AuditRecord, ...]:
        """返回审计记录的不可变快照。"""

        with self._lock:
            return tuple(self._records)

    def write(self, record: AuditRecord) -> None:
        """追加一条已最小化的审计记录。"""

        with self._lock:
            self._records.append(record)


class PermissionEngine:
    """严格按题目指定的一至十步顺序作三态决策，绝不执行 handler。"""

    _HARD_DENY = re.compile(r"(?:\brm\s+-rf\b|\bmkfs\b|\bshutdown\b)", re.I)
    _SHELL_CONFIRM = re.compile(r"(?:\bsudo\b|\bcurl\b|[|;&><])", re.I)

    def __init__(self, approvals: ApprovalStore, allow_rules: frozenset[str] = frozenset()) -> None:
        """注入审批存储和教学用 allow 规则。"""

        self._approvals, self._allow_rules = approvals, allow_rules

    def decide(self, definition: ToolDefinition, arguments: BaseModel, context: ExecutionContext) -> Decision:
        """以固定顺序返回决策；高风险审批位于 bypass 和 allow 之前。"""

        command = str(getattr(arguments, "command", ""))
        # 1. deny 规则。
        if definition.policy.effect == "shell" and self._HARD_DENY.search(command):
            return Decision("deny", "DENY_RULE", "命令命中硬拒绝规则", "deny_rule")
        # 2. plan 仅只读。
        if context.permission_mode == "plan" and definition.policy.effect != "read":
            return Decision("deny", "PLAN_READ_ONLY", "plan 模式只允许只读工具", "plan")
        # 3. 执行期白名单。
        if definition.name not in context.allowed_tools:
            return Decision("deny", "TOOL_NOT_ALLOWED", "本轮不允许调用该工具", "allowed_tools")
        # 4. RBAC。
        if definition.policy.permission not in context.permissions:
            return Decision("deny", "PERMISSION_DENIED", "当前身份缺少工具权限", "rbac")
        # 5. 业务预检查。
        failed = definition.precheck(arguments, context)
        if failed:
            return failed
        # 6. 参数绑定审批。
        if definition.policy.risk == "high" or definition.policy.requires_approval:
            if not self._approvals.consume(context.approval_id, context, definition.name, arguments.model_dump(mode="json")):
                return Decision("confirm", "APPROVAL_REQUIRED", "需要一次性参数绑定审批", "approval")
        # 7. bypass 只能到这里才生效。
        if context.permission_mode == "bypassPermissions":
            return Decision("allow", "BYPASS_ALLOWED", "已跳过普通确认", "bypass")
        # 8. allow 规则。
        if definition.name in self._allow_rules:
            return Decision("allow", "ALLOW_RULE", "命中允许规则", "allow_rule")
        # 9. 普通危险 Shell 需要确认；生产环境应采用窄工具、AST、沙箱和 fail-closed。
        if definition.policy.effect == "shell" and self._SHELL_CONFIRM.search(command):
            return Decision("confirm", "SHELL_CONFIRMATION_REQUIRED", "命令需要人工确认", "shell_review")
        # 10. 默认允许。
        return Decision("allow", "ALLOWED", "治理检查通过", "default")


@dataclass(frozen=True)
class PreparedInvocation:
    """封装 prepare 的无副作用输出。"""

    call: ToolCall
    context: ExecutionContext
    definition: ToolDefinition | None
    arguments: BaseModel | None
    decision: Decision
    started_at: float


@dataclass(frozen=True)
class ExecutionOutcome:
    """封装 execute 的受控结果，不携带异常堆栈。"""

    success: bool
    code: str
    content: Mapping[str, Any]
    retryable: bool


class RetryableToolError(RuntimeError):
    """表示只读或真正幂等工具可有限重试的暂时失败。"""


class ToolRuntime:
    """提供离线、CLI、测试及下一轮 Provider 共用的唯一执行入口。"""

    _SENSITIVE_KEYS = ("token", "secret", "password", "authorization")
    _EMAIL = re.compile(r"\b([A-Za-z0-9._%+-])[^@\s]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")

    def __init__(self, definitions: Sequence[ToolDefinition], engine: PermissionEngine, audit: AuditSink) -> None:
        """注册工具并保存唯一权限引擎和审计出口。"""

        self._definitions = {definition.name: definition for definition in definitions}
        self._engine, self._audit = engine, audit

    def discover(self, context: ExecutionContext) -> list[dict[str, Any]]:
        """向模型只投影发现期白名单、描述和 JSON Schema。"""

        return [{"type": "function", "function": {"name": item.name, "description": item.description, "parameters": item.argument_model.model_json_schema()}} for name, item in sorted(self._definitions.items()) if name in context.allowed_tools]

    def validate_arguments(self, call: ToolCall) -> BaseModel:
        """校验工具参数并生成规范审批参数。"""

        return self._definitions[call.name].argument_model.model_validate(call.arguments)

    def invoke(self, call: ToolCall, context: ExecutionContext) -> ToolResult:
        """唯一生命周期：prepare 后仅 allow 执行，最后统一 finalize。"""

        prepared = self.prepare(call, context)
        outcome = self.execute(prepared) if prepared.decision.state == "allow" else None
        return self.finalize(prepared, outcome)

    def prepare(self, call: ToolCall, context: ExecutionContext) -> PreparedInvocation:
        """查找工具、严格校验参数并在 handler 前进行三态治理。"""

        started = time.perf_counter()
        definition = self._definitions.get(call.name)
        if not definition:
            return PreparedInvocation(call, context, None, None, Decision("deny", "TOOL_NOT_FOUND", "工具不存在", "registry"), started)
        try:
            arguments = definition.argument_model.model_validate(call.arguments)
        except ValidationError:
            return PreparedInvocation(call, context, definition, None, Decision("deny", "INVALID_ARGUMENTS", "工具参数不符合 Schema", "pydantic"), started)
        return PreparedInvocation(call, context, definition, arguments, self._engine.decide(definition, arguments, context), started)

    def execute(self, prepared: PreparedInvocation) -> ExecutionOutcome:
        """只执行 allow 调用；写且非幂等超时返回未知状态且禁止重放。"""

        assert prepared.definition and prepared.arguments
        policy, definition = prepared.definition.policy, prepared.definition
        retry_safe = policy.effect == "read" or policy.idempotent
        attempts = 1 + (policy.max_retries if retry_safe else 0)
        for index in range(attempts):
            try:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(definition.handler, prepared.arguments, prepared.context)
                    return ExecutionOutcome(True, "OK", dict(future.result(timeout=policy.timeout_seconds)), False)
            except FutureTimeoutError:
                if policy.effect == "write" and not policy.idempotent:
                    return ExecutionOutcome(False, "TIMEOUT_UNKNOWN", {"message": "写操作超时，结果未知，禁止重放"}, False)
                if index + 1 == attempts:
                    return ExecutionOutcome(False, "TIMEOUT", {"message": "工具执行超时"}, True)
            except RetryableToolError:
                if index + 1 == attempts:
                    return ExecutionOutcome(False, "TEMPORARY_FAILURE", {"message": "工具暂时不可用"}, retry_safe)
            except Exception:
                return ExecutionOutcome(False, "HANDLER_ERROR", {"message": "工具执行失败"}, False)
        raise AssertionError("执行循环必须返回结果")

    def finalize(self, prepared: PreparedInvocation, outcome: ExecutionOutcome | None) -> ToolResult:
        """投影与脱敏结果，写入决策和执行审计，生成稳定 ToolResult。"""

        latency = max(0, int((time.perf_counter() - prepared.started_at) * 1000))
        keys = tuple(sorted(map(str, prepared.call.arguments.keys())))
        self._audit.write(AuditRecord(prepared.context.trace_id, prepared.call.tool_call_id, prepared.call.name, prepared.context.user_id, prepared.context.tenant_id, "decision", prepared.decision.state, prepared.decision.code, keys, latency))
        if prepared.decision.state != "allow":
            return ToolResult(prepared.call.tool_call_id, prepared.call.name, False, prepared.decision.state, prepared.decision.code, {"message": prepared.decision.reason}, False)
        assert outcome and prepared.definition
        content = self._redact({name: outcome.content[name] for name in prepared.definition.result_fields if name in outcome.content})
        self._audit.write(AuditRecord(prepared.context.trace_id, prepared.call.tool_call_id, prepared.call.name, prepared.context.user_id, prepared.context.tenant_id, "execution", "executed" if outcome.success else "failed", outcome.code, keys, latency))
        return ToolResult(prepared.call.tool_call_id, prepared.call.name, outcome.success, "allow", outcome.code, content, outcome.retryable)

    @classmethod
    def _redact(cls, value: Any, key: str = "") -> Any:
        """按敏感键名和邮箱格式递归脱敏结果。"""

        if any(part in key.lower() for part in cls._SENSITIVE_KEYS):
            return "[REDACTED]"
        if isinstance(value, Mapping):
            return {name: cls._redact(item, str(name)) for name, item in value.items()}
        if isinstance(value, list):
            return [cls._redact(item, key) for item in value]
        return cls._EMAIL.sub(r"\1***@\2", value) if isinstance(value, str) else value


@dataclass
class DemoServices:
    """保存安全的内存订单和可断言的副作用计数。"""

    orders: dict[str, dict[str, Any]] = field(default_factory=lambda: {"ORD-1001": {"tenant_id": "tenant-a", "status": "PAID", "refundable_amount": 500, "customer_email": "customer@example.com", "access_token": "demo-access-token"}})
    refund_executions: int = 0
    shell_executions: int = 0


@dataclass(frozen=True)
class DemoEnvironment:
    """暴露离线演示和测试需要的 Runtime、服务、审批与审计。"""

    runtime: ToolRuntime
    services: DemoServices
    approvals: ApprovalStore
    audit: AuditSink


def make_context(permission_mode: PermissionMode = "default", approval_id: str | None = None, permissions: frozenset[str] | None = None, allowed_tools: frozenset[str] | None = None) -> ExecutionContext:
    """构造可信离线上下文，身份字段不来自 ToolCall。"""

    return ExecutionContext("trace-step4", "user-1", "tenant-a", permissions or frozenset({"order:read", "refund:create", "shell:run"}), allowed_tools or frozenset({"get_order", "create_refund", "run_shell"}), permission_mode, approval_id)


def build_demo_environment() -> DemoEnvironment:
    """组装第 4 轮完整离线治理环境，所有 handler 均只由 Runtime 触发。"""

    services, approvals, audit = DemoServices(), ApprovalStore(), AuditSink()
    def order(arguments: BaseModel, context: ExecutionContext) -> Decision | None:
        """在 handler 前验证订单属于当前租户。"""
        order_id = str(getattr(arguments, "order_id"))
        if order_id not in services.orders or services.orders[order_id]["tenant_id"] != context.tenant_id:
            return Decision("deny", "RESOURCE_NOT_FOUND", "订单不存在", "business_precheck")
        return None
    def refund_check(arguments: BaseModel, context: ExecutionContext) -> Decision | None:
        """在 handler 前验证订单状态与退款额度。"""
        failed = order(arguments, context)
        if failed: return failed
        item, amount = services.orders[str(getattr(arguments, "order_id"))], int(getattr(arguments, "amount"))
        if item["status"] != "PAID": return Decision("deny", "ORDER_NOT_REFUNDABLE", "订单状态不可退款", "business_precheck")
        if amount > item["refundable_amount"]: return Decision("deny", "AMOUNT_EXCEEDS_LIMIT", "退款金额超过可退额度", "business_precheck")
        return None
    def none(arguments: BaseModel, context: ExecutionContext) -> Decision | None:
        """表示该工具无需额外业务检查。"""
        del arguments, context; return None
    def get_order(arguments: BaseModel, context: ExecutionContext) -> Mapping[str, Any]:
        """读取订单；finalize 会统一投影和脱敏。"""
        item = services.orders[str(getattr(arguments, "order_id"))]
        del context
        return {"order_id": getattr(arguments, "order_id"), "status": item["status"], "refundable_amount": item["refundable_amount"], "customer_email": item["customer_email"], "access_token": item["access_token"], "internal": "not exposed"}
    def refund(arguments: BaseModel, context: ExecutionContext) -> Mapping[str, Any]:
        """模拟非幂等退款副作用，不连接真实支付系统。"""
        item = services.orders[str(getattr(arguments, "order_id"))]
        del context
        services.refund_executions += 1; item["refundable_amount"] -= int(getattr(arguments, "amount"))
        return {"refund_id": f"REF-{services.refund_executions:04d}", "amount": getattr(arguments, "amount"), "status": "CREATED"}
    def shell(arguments: BaseModel, context: ExecutionContext) -> Mapping[str, Any]:
        """仅记录模拟副作用，绝不启动子进程。"""
        del context
        services.shell_executions += 1; return {"command": getattr(arguments, "command"), "status": "SIMULATED"}
    definitions = [
        ToolDefinition("get_order", "查询当前租户订单", GetOrderArguments, ToolPolicy("read", "low", "order:read", False, 1, 1, True), get_order, order, ("order_id", "status", "refundable_amount", "customer_email", "access_token")),
        ToolDefinition("create_refund", "创建需要人工审批的退款", CreateRefundArguments, ToolPolicy("write", "high", "refund:create", True, 1, 0, False), refund, refund_check, ("refund_id", "amount", "status")),
        ToolDefinition("run_shell", "模拟受治理的 Shell", RunShellArguments, ToolPolicy("shell", "medium", "shell:run", False, 1, 0, False), shell, none, ("command", "status")),
    ]
    return DemoEnvironment(ToolRuntime(definitions, PermissionEngine(approvals), audit), services, approvals, audit)


def main() -> None:
    """运行第 4 轮离线闭环：查询、确认、审批后的退款。"""

    environment, context = build_demo_environment(), make_context()
    call = ToolCall("refund-step4", "create_refund", {"order_id": "ORD-1001", "amount": 100, "reason": "客户退款"})
    print(environment.runtime.invoke(ToolCall("query-step4", "get_order", {"order_id": "ORD-1001"}), context).to_json())
    print(environment.runtime.invoke(call, context).to_json())
    approval_id = environment.approvals.issue(context, call.name, environment.runtime.validate_arguments(call).model_dump(mode="json"))
    print(environment.runtime.invoke(call, replace(context, approval_id=approval_id)).to_json())
    print(f"refund_executions={environment.services.refund_executions}, audit_records={len(environment.audit.records)}")


if __name__ == "__main__":
    main()
