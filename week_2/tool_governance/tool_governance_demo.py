"""最小但完整的 Agent 工具治理 Runtime 教学示例。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Callable, Literal, Mapping, Sequence
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError


DecisionState = Literal["allow", "deny", "confirm"]
Effect = Literal["read", "write", "shell"]
Risk = Literal["low", "medium", "high"]
PermissionMode = Literal["default", "plan", "bypassPermissions"]


class StrictToolArguments(BaseModel):
    """约束模型只能提交声明过的严格业务参数。"""

    model_config = ConfigDict(extra="forbid", strict=True)


class GetOrderArguments(StrictToolArguments):
    """查询订单的模型可见参数。"""

    order_id: str = Field(pattern=r"^ORD-[0-9]{4,12}$")


class CreateRefundArguments(StrictToolArguments):
    """创建退款的模型可见参数。"""

    order_id: str = Field(pattern=r"^ORD-[0-9]{4,12}$")
    amount: int = Field(gt=0, le=100_000)
    reason: str = Field(min_length=3, max_length=200)


class RunShellArguments(StrictToolArguments):
    """教学 Shell 的模型可见参数。"""

    command: str = Field(min_length=1, max_length=200)


@dataclass(frozen=True)
class ToolCall:
    """表示 Provider 转换后的不可信工具调用。"""

    tool_call_id: str
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True)
class ToolResult:
    """表示回填给模型的稳定工具结果协议。"""

    tool_call_id: str
    tool_name: str
    success: bool
    decision: DecisionState
    code: str
    content: Any
    retryable: bool

    def to_json(self) -> str:
        """将工具结果序列化为 Provider 可回填的 JSON。"""

        return json.dumps(asdict(self), ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class ToolPolicy:
    """声明工具的权限、风险与副作用执行语义。"""

    effect: Effect
    risk: Risk
    permission: str
    requires_approval: bool
    timeout_seconds: float
    max_retries: int
    idempotent: bool


@dataclass(frozen=True)
class ExecutionContext:
    """保存仅由可信服务端构造的身份与治理上下文。"""

    trace_id: str
    user_id: str
    tenant_id: str
    permissions: frozenset[str]
    allowed_tools: frozenset[str]
    permission_mode: PermissionMode = "default"
    approval_id: str | None = None


@dataclass(frozen=True)
class Decision:
    """描述权限引擎的三态决策。"""

    state: DecisionState
    code: str
    reason: str
    source: str


ToolHandler = Callable[[BaseModel, ExecutionContext], Mapping[str, Any]]
ToolPrecheck = Callable[[BaseModel, ExecutionContext], Decision | None]
TargetNormalizer = Callable[[BaseModel], Mapping[str, Any]]


@dataclass(frozen=True)
class ToolDefinition:
    """聚合工具实现；Runtime 只向模型投影名称、描述与 Schema。"""

    name: str
    description: str
    argument_model: type[BaseModel]
    policy: ToolPolicy
    handler: ToolHandler
    precheck: ToolPrecheck
    normalize_target: TargetNormalizer
    result_fields: tuple[str, ...]


@dataclass
class ApprovalRecord:
    """保存与身份、工具和规范参数绑定的一次性审批。"""

    approval_id: str
    user_id: str
    tenant_id: str
    tool_name: str
    arguments_sha256: str
    expires_at: float
    used: bool = False


class ApprovalStore:
    """以原子方式签发和消费一次性参数绑定审批。"""

    def __init__(self) -> None:
        self._records: dict[str, ApprovalRecord] = {}
        self._lock = threading.Lock()

    def issue(
        self,
        context: ExecutionContext,
        tool_name: str,
        canonical_arguments: Mapping[str, Any],
        ttl_seconds: float = 300,
    ) -> str:
        """为可信服务端已经展示给用户的规范参数签发审批。"""

        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds 必须大于 0")
        approval_id = f"apr_{uuid4().hex}"
        record = ApprovalRecord(
            approval_id=approval_id,
            user_id=context.user_id,
            tenant_id=context.tenant_id,
            tool_name=tool_name,
            arguments_sha256=arguments_digest(canonical_arguments),
            expires_at=time.time() + ttl_seconds,
        )
        with self._lock:
            self._records[approval_id] = record
        return approval_id

    def consume(
        self,
        approval_id: str | None,
        context: ExecutionContext,
        tool_name: str,
        canonical_arguments: Mapping[str, Any],
    ) -> bool:
        """原子校验并消费审批，任何不匹配都按未审批处理。"""

        if not approval_id:
            return False
        expected_digest = arguments_digest(canonical_arguments)
        with self._lock:
            record = self._records.get(approval_id)
            if record is None or record.used or record.expires_at <= time.time():
                return False
            matches = (
                record.user_id == context.user_id
                and record.tenant_id == context.tenant_id
                and record.tool_name == tool_name
                and record.arguments_sha256 == expected_digest
            )
            if not matches:
                return False
            record.used = True
            return True


@dataclass(frozen=True)
class AuditRecord:
    """保存不含参数值、客户资料和异常堆栈的审计事件。"""

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
    """线程安全地收集最小化审计记录。"""

    def __init__(self) -> None:
        self._records: list[AuditRecord] = []
        self._lock = threading.Lock()

    @property
    def records(self) -> tuple[AuditRecord, ...]:
        """返回审计记录的只读快照。"""

        with self._lock:
            return tuple(self._records)

    def write(self, record: AuditRecord) -> None:
        """写入一条经过最小化处理的审计记录。"""

        with self._lock:
            self._records.append(record)


def arguments_digest(arguments: Mapping[str, Any]) -> str:
    """对递归排序后的稳定 JSON 参数计算 SHA-256。"""

    canonical_json = json.dumps(
        arguments,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class PermissionEngine:
    """按不可交换的固定顺序执行三态治理决策。"""

    _HARD_SHELL_DENY = re.compile(
        r"(?:\brm\s+-rf\b|\bmkfs\b|\bshutdown\b|\bformat\s+[a-z]:|\bdel\s+/[sq]\b|\bdrop\s+database\b)",
        re.IGNORECASE,
    )
    _SHELL_REVIEW = re.compile(r"(?:\bsudo\b|\bcurl\b|\bwget\b|[|;&><])", re.IGNORECASE)

    def __init__(
        self,
        approval_store: ApprovalStore,
        allow_rules: frozenset[str] | None = None,
    ) -> None:
        self._approval_store = approval_store
        self._allow_rules = allow_rules or frozenset()

    def decide(
        self,
        definition: ToolDefinition,
        arguments: BaseModel,
        context: ExecutionContext,
    ) -> Decision:
        """严格按十个步骤返回 allow、deny 或 confirm，绝不执行 handler。"""

        # 1. deny 规则必须最先执行，bypass 也不能覆盖硬拒绝。
        hard_deny = self._hard_deny(definition, arguments)
        if hard_deny is not None:
            return hard_deny

        # 2. plan 模式由执行层强制只读。
        if context.permission_mode == "plan" and definition.policy.effect != "read":
            return Decision("deny", "PLAN_READ_ONLY", "plan 模式只允许只读工具", "plan")

        # 3. 执行期重新检查本轮工具白名单。
        if definition.name not in context.allowed_tools:
            return Decision("deny", "TOOL_NOT_ALLOWED", "本轮不允许调用该工具", "allowed_tools")

        # 4. RBAC 权限。
        if definition.policy.permission not in context.permissions:
            return Decision("deny", "PERMISSION_DENIED", "当前身份缺少工具权限", "rbac")

        # 5. 租户归属、状态与额度等业务预检查。
        precheck_decision = definition.precheck(arguments, context)
        if precheck_decision is not None:
            return precheck_decision

        canonical_arguments = arguments.model_dump(mode="json")

        # 6. 高风险或显式要求审批的工具必须消费参数绑定审批。
        needs_approval = definition.policy.risk == "high" or definition.policy.requires_approval
        if needs_approval and not self._approval_store.consume(
            context.approval_id,
            context,
            definition.name,
            canonical_arguments,
        ):
            return Decision(
                "confirm",
                "APPROVAL_REQUIRED",
                "需要与本次身份和参数绑定的一次性审批",
                "approval",
            )

        # 7. bypassPermissions 只在 1-6 全部通过后跳过普通确认。
        if context.permission_mode == "bypassPermissions":
            return Decision("allow", "BYPASS_ALLOWED", "已跳过普通确认", "bypass")

        # 8. 显式 allow 规则。
        if definition.name in self._allow_rules:
            return Decision("allow", "ALLOW_RULE", "命中允许规则", "allow_rule")

        # 9. 教学 Shell 的普通危险模式需要确认；硬危险命令已在步骤 1 拒绝。
        if definition.policy.effect == "shell":
            command = str(getattr(arguments, "command", ""))
            if self._SHELL_REVIEW.search(command):
                return Decision(
                    "confirm",
                    "SHELL_CONFIRMATION_REQUIRED",
                    "Shell 命令包含需要人工确认的模式",
                    "shell_review",
                )

        # 10. 默认允许。
        return Decision("allow", "ALLOWED", "治理检查通过", "default")

    def _hard_deny(
        self,
        definition: ToolDefinition,
        arguments: BaseModel,
    ) -> Decision | None:
        """识别教学示例中的硬拒绝 Shell 模式。"""

        if definition.policy.effect != "shell":
            return None
        command = str(getattr(arguments, "command", ""))
        if not self._HARD_SHELL_DENY.search(command):
            return None
        # 生产环境应优先使用窄工具、AST、沙箱、最小权限和 fail-closed，不能依赖正则兜底。
        return Decision("deny", "DENY_RULE", "命令命中硬拒绝规则", "deny_rule")


@dataclass(frozen=True)
class PreparedInvocation:
    """保存 prepare 阶段输出，供 execute 与 finalize 使用。"""

    call: ToolCall
    context: ExecutionContext
    definition: ToolDefinition | None
    arguments: BaseModel | None
    decision: Decision
    started_at: float


@dataclass(frozen=True)
class ExecutionOutcome:
    """保存 execute 阶段的受控结果。"""

    success: bool
    code: str
    content: Mapping[str, Any]
    retryable: bool
    attempts: int


class RetryableToolError(RuntimeError):
    """表示只读或幂等工具可以有限重试的瞬时故障。"""


class ToolRuntime:
    """提供模型、CLI、离线演示和测试共用的唯一工具执行入口。"""

    _SENSITIVE_KEY_PARTS = ("token", "secret", "password", "authorization")
    _EMAIL = re.compile(r"\b([A-Za-z0-9._%+-])[^@\s]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")

    def __init__(
        self,
        definitions: Sequence[ToolDefinition],
        permission_engine: PermissionEngine,
        audit_sink: AuditSink,
    ) -> None:
        self._definitions = {definition.name: definition for definition in definitions}
        if len(self._definitions) != len(definitions):
            raise ValueError("工具名称必须唯一")
        self._permission_engine = permission_engine
        self._audit_sink = audit_sink

    def discover(self, context: ExecutionContext) -> list[dict[str, Any]]:
        """仅投影发现期白名单内工具的名称、描述和 JSON Schema。"""

        discovered: list[dict[str, Any]] = []
        for name in sorted(context.allowed_tools):
            definition = self._definitions.get(name)
            if definition is None:
                continue
            discovered.append(
                {
                    "type": "function",
                    "function": {
                        "name": definition.name,
                        "description": definition.description,
                        "parameters": definition.argument_model.model_json_schema(),
                    },
                }
            )
        return discovered

    def validate_arguments(self, call: ToolCall) -> BaseModel:
        """使用注册工具的 Pydantic Schema 生成规范审批参数。"""

        definition = self._definitions.get(call.name)
        if definition is None:
            raise KeyError(call.name)
        return definition.argument_model.model_validate(call.arguments)

    def invoke(self, call: ToolCall, context: ExecutionContext) -> ToolResult:
        """按 prepare、execute、finalize 的唯一生命周期治理工具调用。"""

        prepared = self.prepare(call, context)
        outcome = self.execute(prepared) if prepared.decision.state == "allow" else None
        return self.finalize(prepared, outcome)

    def prepare(self, call: ToolCall, context: ExecutionContext) -> PreparedInvocation:
        """查找工具、校验不可信参数并执行权限三态决策。"""

        started_at = time.perf_counter()
        definition = self._definitions.get(call.name)
        if definition is None:
            return PreparedInvocation(
                call,
                context,
                None,
                None,
                Decision("deny", "TOOL_NOT_FOUND", "工具不存在", "registry"),
                started_at,
            )
        try:
            arguments = definition.argument_model.model_validate(call.arguments)
        except ValidationError:
            return PreparedInvocation(
                call,
                context,
                definition,
                None,
                Decision("deny", "INVALID_ARGUMENTS", "工具参数不符合 Schema", "pydantic"),
                started_at,
            )
        decision = self._permission_engine.decide(definition, arguments, context)
        return PreparedInvocation(call, context, definition, arguments, decision, started_at)

    def execute(self, prepared: PreparedInvocation) -> ExecutionOutcome:
        """只在 allow 后执行 handler，并按只读/幂等属性限制重试。"""

        if prepared.decision.state != "allow" or prepared.definition is None or prepared.arguments is None:
            raise RuntimeError("execute 只能接收 allow 的 PreparedInvocation")

        policy = prepared.definition.policy
        retry_safe = policy.effect == "read" or policy.idempotent
        max_attempts = 1 + (policy.max_retries if retry_safe else 0)

        for attempt in range(1, max_attempts + 1):
            try:
                content = self._execute_once(prepared.definition, prepared.arguments, prepared.context)
                return ExecutionOutcome(True, "OK", content, False, attempt)
            except FutureTimeoutError:
                if policy.effect == "write" and not policy.idempotent:
                    return ExecutionOutcome(
                        False,
                        "TIMEOUT_UNKNOWN",
                        {"message": "写操作超时，结果未知，禁止直接重放"},
                        False,
                        attempt,
                    )
                if attempt == max_attempts:
                    return ExecutionOutcome(
                        False,
                        "TIMEOUT",
                        {"message": "工具执行超时"},
                        True,
                        attempt,
                    )
            except RetryableToolError:
                if not retry_safe or attempt == max_attempts:
                    return ExecutionOutcome(
                        False,
                        "TEMPORARY_FAILURE",
                        {"message": "工具暂时不可用"},
                        retry_safe,
                        attempt,
                    )
            except Exception:
                return ExecutionOutcome(
                    False,
                    "HANDLER_ERROR",
                    {"message": "工具执行失败"},
                    False,
                    attempt,
                )

        raise AssertionError("重试循环必须返回结果")

    def finalize(
        self,
        prepared: PreparedInvocation,
        outcome: ExecutionOutcome | None,
    ) -> ToolResult:
        """投影并递归脱敏结果、写入审计，再生成稳定 ToolResult。"""

        latency_ms = max(0, int((time.perf_counter() - prepared.started_at) * 1000))
        argument_keys = tuple(sorted(str(key) for key in prepared.call.arguments.keys()))
        self._audit_sink.write(
            AuditRecord(
                trace_id=prepared.context.trace_id,
                tool_call_id=prepared.call.tool_call_id,
                tool_name=prepared.call.name,
                user_id=prepared.context.user_id,
                tenant_id=prepared.context.tenant_id,
                phase="decision",
                status=prepared.decision.state,
                code=prepared.decision.code,
                argument_keys=argument_keys,
                latency_ms=latency_ms,
            )
        )

        if prepared.decision.state != "allow":
            return ToolResult(
                tool_call_id=prepared.call.tool_call_id,
                tool_name=prepared.call.name,
                success=False,
                decision=prepared.decision.state,
                code=prepared.decision.code,
                content={"message": prepared.decision.reason},
                retryable=False,
            )

        if outcome is None or prepared.definition is None:
            raise RuntimeError("allow 决策必须具有执行结果和工具定义")

        projected = self._project_result(outcome.content, prepared.definition.result_fields)
        safe_content = self._redact(projected)
        self._audit_sink.write(
            AuditRecord(
                trace_id=prepared.context.trace_id,
                tool_call_id=prepared.call.tool_call_id,
                tool_name=prepared.call.name,
                user_id=prepared.context.user_id,
                tenant_id=prepared.context.tenant_id,
                phase="execution",
                status="executed" if outcome.success else "failed",
                code=outcome.code,
                argument_keys=argument_keys,
                latency_ms=latency_ms,
            )
        )
        return ToolResult(
            tool_call_id=prepared.call.tool_call_id,
            tool_name=prepared.call.name,
            success=outcome.success,
            decision="allow",
            code=outcome.code,
            content=safe_content,
            retryable=outcome.retryable,
        )

    @staticmethod
    def _execute_once(
        definition: ToolDefinition,
        arguments: BaseModel,
        context: ExecutionContext,
    ) -> Mapping[str, Any]:
        """在独立线程中执行一次 handler 并施加超时边界。"""

        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"tool-{definition.name}")
        future = executor.submit(definition.handler, arguments, context)
        try:
            result = future.result(timeout=definition.policy.timeout_seconds)
            if not isinstance(result, Mapping):
                raise TypeError("handler 必须返回 Mapping")
            return result
        except FutureTimeoutError:
            future.cancel()
            raise
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def _project_result(content: Mapping[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
        """仅保留工具定义声明允许返回给模型的字段。"""

        return {field_name: content[field_name] for field_name in fields if field_name in content}

    @classmethod
    def _redact(cls, value: Any) -> Any:
        """递归脱敏敏感键值与任意层级字符串中的邮箱。"""

        if isinstance(value, Mapping):
            redacted: dict[str, Any] = {}
            for key, item in value.items():
                key_text = str(key)
                if any(part in key_text.lower() for part in cls._SENSITIVE_KEY_PARTS):
                    redacted[key_text] = "[REDACTED]"
                else:
                    redacted[key_text] = cls._redact(item)
            return redacted
        if isinstance(value, (list, tuple)):
            return [cls._redact(item) for item in value]
        if isinstance(value, str):
            return cls._EMAIL.sub(lambda match: f"{match.group(1)}***@{match.group(2)}", value)
        return value


@dataclass
class DemoServices:
    """保存教学业务数据和可断言的真实副作用计数。"""

    orders: dict[str, dict[str, Any]] = field(
        default_factory=lambda: {
            "ORD-1001": {
                "tenant_id": "tenant-a",
                "status": "PAID",
                "refundable_amount": 500,
                "customer_email": "customer@example.com",
                "access_token": "demo-access-token",
            }
        }
    )
    refund_executions: int = 0
    shell_executions: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass(frozen=True)
class DemoEnvironment:
    """汇总离线演示和测试共用的真实 Runtime 依赖。"""

    runtime: ToolRuntime
    services: DemoServices
    approvals: ApprovalStore
    audit: AuditSink


def make_context(
    *,
    permissions: frozenset[str] | None = None,
    allowed_tools: frozenset[str] | None = None,
    permission_mode: PermissionMode = "default",
    approval_id: str | None = None,
) -> ExecutionContext:
    """模拟认证中间件在服务端生成可信执行上下文。"""

    return ExecutionContext(
        trace_id=f"trace_{uuid4().hex}",
        user_id="user-1",
        tenant_id="tenant-a",
        permissions=permissions
        if permissions is not None
        else frozenset({"order:read", "refund:create", "shell:run"}),
        allowed_tools=allowed_tools
        if allowed_tools is not None
        else frozenset({"get_order", "create_refund", "run_shell"}),
        permission_mode=permission_mode,
        approval_id=approval_id,
    )


def build_demo_environment() -> DemoEnvironment:
    """组装离线演示、CLI、测试和 Provider 共用的治理 Runtime。"""

    services = DemoServices()
    approvals = ApprovalStore()
    audit = AuditSink()

    def order_for_tenant(order_id: str, context: ExecutionContext) -> dict[str, Any] | None:
        """按租户边界读取订单快照，避免泄漏跨租户资源是否存在。"""

        with services.lock:
            order = services.orders.get(order_id)
            if order is None or order["tenant_id"] != context.tenant_id:
                return None
            return dict(order)

    def get_order_precheck(arguments: BaseModel, context: ExecutionContext) -> Decision | None:
        """在 handler 之前校验查询订单的租户归属。"""

        typed = _require_arguments(arguments, GetOrderArguments)
        if order_for_tenant(typed.order_id, context) is None:
            return Decision("deny", "RESOURCE_NOT_FOUND", "订单不存在", "business_precheck")
        return None

    def refund_precheck(arguments: BaseModel, context: ExecutionContext) -> Decision | None:
        """在 handler 之前校验退款订单归属、状态和可退额度。"""

        typed = _require_arguments(arguments, CreateRefundArguments)
        order = order_for_tenant(typed.order_id, context)
        if order is None:
            return Decision("deny", "RESOURCE_NOT_FOUND", "订单不存在", "business_precheck")
        if order["status"] != "PAID":
            return Decision("deny", "ORDER_NOT_REFUNDABLE", "订单状态不可退款", "business_precheck")
        if typed.amount > order["refundable_amount"]:
            return Decision("deny", "AMOUNT_EXCEEDS_LIMIT", "退款金额超过可退额度", "business_precheck")
        return None

    def no_business_precheck(arguments: BaseModel, context: ExecutionContext) -> Decision | None:
        """表示该教学工具没有额外业务前置条件。"""

        del arguments, context
        return None

    def get_order_handler(arguments: BaseModel, context: ExecutionContext) -> Mapping[str, Any]:
        """返回订单数据；敏感字段将在 finalize 阶段统一脱敏。"""

        typed = _require_arguments(arguments, GetOrderArguments)
        order = order_for_tenant(typed.order_id, context)
        if order is None:
            raise RuntimeError("订单在通过 precheck 后消失")
        return {
            "order_id": typed.order_id,
            "status": order["status"],
            "refundable_amount": order["refundable_amount"],
            "customer_email": order["customer_email"],
            "access_token": order["access_token"],
            "internal_note": "该字段不会被结果投影返回",
        }

    def create_refund_handler(arguments: BaseModel, context: ExecutionContext) -> Mapping[str, Any]:
        """模拟一次非幂等退款写操作并增加真实副作用计数。"""

        typed = _require_arguments(arguments, CreateRefundArguments)
        with services.lock:
            order = services.orders.get(typed.order_id)
            if order is None or order["tenant_id"] != context.tenant_id:
                raise RuntimeError("订单在通过 precheck 后消失")
            services.refund_executions += 1
            order["refundable_amount"] -= typed.amount
            return {
                "refund_id": f"REF-{services.refund_executions:04d}",
                "order_id": typed.order_id,
                "amount": typed.amount,
                "status": "CREATED",
            }

    def run_shell_handler(arguments: BaseModel, context: ExecutionContext) -> Mapping[str, Any]:
        """只记录教学副作用，绝不创建真实 Shell 子进程。"""

        typed = _require_arguments(arguments, RunShellArguments)
        del context
        with services.lock:
            services.shell_executions += 1
        return {"command": typed.command, "status": "SIMULATED"}

    definitions = [
        ToolDefinition(
            name="get_order",
            description="查询当前租户订单的状态和可退款金额",
            argument_model=GetOrderArguments,
            policy=ToolPolicy("read", "low", "order:read", False, 1.0, 1, True),
            handler=get_order_handler,
            precheck=get_order_precheck,
            normalize_target=lambda args: {"order_id": getattr(args, "order_id")},
            result_fields=(
                "order_id",
                "status",
                "refundable_amount",
                "customer_email",
                "access_token",
            ),
        ),
        ToolDefinition(
            name="create_refund",
            description="为当前租户订单创建需要人工审批的退款",
            argument_model=CreateRefundArguments,
            policy=ToolPolicy("write", "high", "refund:create", True, 1.0, 0, False),
            handler=create_refund_handler,
            precheck=refund_precheck,
            normalize_target=lambda args: {"order_id": getattr(args, "order_id")},
            result_fields=("refund_id", "order_id", "amount", "status"),
        ),
        ToolDefinition(
            name="run_shell",
            description="模拟执行受治理的教学 Shell 命令，不启动真实子进程",
            argument_model=RunShellArguments,
            policy=ToolPolicy("shell", "medium", "shell:run", False, 0.5, 0, False),
            handler=run_shell_handler,
            precheck=no_business_precheck,
            normalize_target=lambda args: {"command": getattr(args, "command")},
            result_fields=("command", "status"),
        ),
    ]
    permission_engine = PermissionEngine(approvals)
    runtime = ToolRuntime(definitions, permission_engine, audit)
    return DemoEnvironment(runtime, services, approvals, audit)


def _require_arguments(arguments: BaseModel, expected_type: type[BaseModel]) -> Any:
    """在注册错误时尽早失败，并为闭包 handler 保持清晰类型边界。"""

    if not isinstance(arguments, expected_type):
        raise TypeError(f"期望 {expected_type.__name__}")
    return arguments


def run_offline_demo() -> None:
    """运行无需 API Key 的七组治理与副作用演示。"""

    environment = build_demo_environment()
    runtime = environment.runtime
    context = make_context()

    query = runtime.invoke(ToolCall("call-query", "get_order", {"order_id": "ORD-1001"}), context)
    print("1. 查询成功并脱敏:", query.to_json())

    refund_call = ToolCall(
        "call-refund",
        "create_refund",
        {"order_id": "ORD-1001", "amount": 100, "reason": "客户申请退款"},
    )
    unapproved = runtime.invoke(refund_call, context)
    print("2. 未审批退款:", unapproved.code, unapproved.decision)

    canonical_arguments = runtime.validate_arguments(refund_call).model_dump(mode="json")
    approval_id = environment.approvals.issue(context, refund_call.name, canonical_arguments)
    approved_context = replace(context, approval_id=approval_id)
    approved = runtime.invoke(refund_call, approved_context)
    print("3. 参数绑定审批后退款:", approved.to_json())

    spoof_user = runtime.invoke(
        ToolCall("call-spoof-user", "get_order", {"order_id": "ORD-1001", "user_id": "admin"}),
        context,
    )
    spoof_approval = runtime.invoke(
        ToolCall(
            "call-spoof-approval",
            "create_refund",
            {
                "order_id": "ORD-1001",
                "amount": 1,
                "reason": "伪造审批字段",
                "approved": True,
            },
        ),
        context,
    )
    print("4. 伪造服务端字段:", spoof_user.code, spoof_approval.code)

    bypass_context = replace(context, permission_mode="bypassPermissions")
    denied_shell = runtime.invoke(
        ToolCall("call-shell", "run_shell", {"command": "rm -rf /"}),
        bypass_context,
    )
    print("5. bypass 下硬拒绝 Shell:", denied_shell.code, denied_shell.decision)

    plan_context = replace(context, permission_mode="plan")
    plan_refund = runtime.invoke(replace(refund_call, tool_call_id="call-plan"), plan_context)
    print("6. plan 拒绝退款:", plan_refund.code, plan_refund.decision)

    print(
        "7. 最终副作用与审计:",
        f"refund_executions={environment.services.refund_executions}",
        f"shell_executions={environment.services.shell_executions}",
        f"audit_records={len(environment.audit.records)}",
    )


async def run_deepseek_agent_loop(
    runtime: ToolRuntime,
    context: ExecutionContext,
    user_input: str,
) -> None:
    """通过 OpenAI-compatible 流式协议运行最多八轮 DeepSeek Agent Loop。"""

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DeepSeek 模式需要设置 DEEPSEEK_API_KEY")

    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_input}]

    for _round_number in range(1, 9):
        stream = await client.chat.completions.create(
            model=model,
            messages=messages,
            tools=runtime.discover(context),
            stream=True,
            extra_body={"thinking": {"type": "disabled"}},
        )
        text_parts: list[str] = []
        accumulated_calls: dict[int, dict[str, str]] = {}

        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                text_parts.append(delta.content)
                print(delta.content, end="", flush=True)
            for provider_call in delta.tool_calls or []:
                bucket = accumulated_calls.setdefault(
                    provider_call.index,
                    {"id": "", "name": "", "arguments": ""},
                )
                if provider_call.id:
                    bucket["id"] += provider_call.id
                if provider_call.function and provider_call.function.name:
                    bucket["name"] += provider_call.function.name
                if provider_call.function and provider_call.function.arguments:
                    bucket["arguments"] += provider_call.function.arguments

        if text_parts:
            print()
        if not accumulated_calls:
            return

        provider_tool_calls = [
            {
                "id": item["id"],
                "type": "function",
                "function": {"name": item["name"], "arguments": item["arguments"]},
            }
            for _, item in sorted(accumulated_calls.items())
        ]
        messages.append(
            {
                "role": "assistant",
                "content": "".join(text_parts) or None,
                "tool_calls": provider_tool_calls,
            }
        )

        confirmation_required = False
        for provider_call in provider_tool_calls:
            try:
                arguments = json.loads(provider_call["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                arguments = {"_invalid_json": True}
            internal_call = ToolCall(
                tool_call_id=provider_call["id"],
                name=provider_call["function"]["name"],
                arguments=arguments,
            )
            # Provider 只做协议转换；所有真实调用都进入同一个 Runtime.invoke()。
            result = runtime.invoke(internal_call, context)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": result.tool_call_id,
                    "content": result.to_json(),
                }
            )
            confirmation_required = confirmation_required or result.decision == "confirm"

        if confirmation_required:
            print("工具调用需要人工确认，Agent Loop 已暂停。")
            return

    print("Agent Loop 已达到最多 8 轮。")


def main() -> None:
    """解析命令行参数并选择离线演示或可选 DeepSeek 模式。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deepseek", action="store_true", help="启用可选 DeepSeek Agent Loop")
    parser.add_argument("--prompt", default="请查询订单 ORD-1001", help="DeepSeek 模式用户输入")
    args = parser.parse_args()

    if args.deepseek:
        environment = build_demo_environment()
        asyncio.run(run_deepseek_agent_loop(environment.runtime, make_context(), args.prompt))
    else:
        run_offline_demo()


if __name__ == "__main__":
    main()
