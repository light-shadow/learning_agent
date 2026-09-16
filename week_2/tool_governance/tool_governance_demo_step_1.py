"""第 1 轮：不可信 Tool Call 的对象模型、严格 Pydantic Schema 与稳定 ToolResult。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field


DecisionState = Literal["allow", "deny", "confirm"]
Effect = Literal["read", "write", "shell"]
Risk = Literal["low", "medium", "high"]


class StrictToolArguments(BaseModel):
    """定义模型可见的严格业务参数基类，拒绝伪造服务端字段。"""

    model_config = ConfigDict(extra="forbid", strict=True)


class GetOrderArguments(StrictToolArguments):
    """定义查询订单时模型唯一可提交的字段。"""

    order_id: str = Field(pattern=r"^ORD-[0-9]{4,12}$")


class CreateRefundArguments(StrictToolArguments):
    """定义退款业务候选参数，不包含用户、租户或审批信息。"""

    order_id: str = Field(pattern=r"^ORD-[0-9]{4,12}$")
    amount: int = Field(gt=0, le=100_000)
    reason: str = Field(min_length=3, max_length=200)


class RunShellArguments(StrictToolArguments):
    """定义教学 Shell 的候选命令字段。"""

    command: str = Field(min_length=1, max_length=200)


@dataclass(frozen=True)
class ToolCall:
    """保存 Provider 转换后的不可信工具调用。"""

    tool_call_id: str
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True)
class ToolResult:
    """定义可稳定回填给 Provider 的工具结果协议。"""

    tool_call_id: str
    tool_name: str
    success: bool
    decision: DecisionState
    code: str
    content: Any
    retryable: bool

    def to_json(self) -> str:
        """将结果编码为紧凑 JSON，保留原始 tool_call_id。"""

        return json.dumps(asdict(self), ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class ToolPolicy:
    """声明工具的治理属性；第 1 轮只建模，尚不执行。"""

    effect: Effect
    risk: Risk
    permission: str
    requires_approval: bool
    timeout_seconds: float
    max_retries: int
    idempotent: bool


def model_visible_tools() -> list[dict[str, Any]]:
    """仅生成名称、描述和 Schema 的安全模型视图。"""

    return [
        {"name": "get_order", "description": "查询订单", "parameters": GetOrderArguments.model_json_schema()},
        {"name": "create_refund", "description": "创建退款", "parameters": CreateRefundArguments.model_json_schema()},
        {"name": "run_shell", "description": "模拟 Shell", "parameters": RunShellArguments.model_json_schema()},
    ]


def main() -> None:
    """输出第 1 轮 Schema，便于观察模型不能伪造的服务端字段。"""

    print(json.dumps(model_visible_tools(), ensure_ascii=False, indent=2))
    rejected = False
    try:
        CreateRefundArguments.model_validate(
            {"order_id": "ORD-1001", "amount": 100, "reason": "客户退款", "approved": True}
        )
    except Exception:
        rejected = True
    print(f"伪造 approved 字段被拒绝: {rejected}")


if __name__ == "__main__":
    main()
