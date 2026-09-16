"""search_orders 的最小 Function Calling / Tool Use 离线练习。"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any


# 第 1 步：工具输入契约。这里使用 JSON Schema，供模型理解可传入的参数。
SEARCH_ORDERS_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "member_id": {
            "type": "string",
            "description": "会员标识。",
            "minLength": 1,
        },
        "order_id": {
            "type": "string",
            "description": "可选：精确查询某个订单号。",
            "minLength": 1,
        },
        "status": {
            "type": "string",
            "description": "可选：按订单状态筛选。",
            "enum": ["PAID", "COMPLETED", "CANCELLED"],
        },
    },
    "required": ["member_id"],
}


# 第 2 步：这是发送给模型的唯一 Tool JSON；不暴露 handler、权限或内部依赖。
SEARCH_ORDERS_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search_orders",
        "description": "查询指定会员的模拟咖啡订单；可按订单号或状态进一步筛选。",
        "parameters": SEARCH_ORDERS_INPUT_SCHEMA,
        "strict": True,
    },
}


MOCK_ORDERS: tuple[dict[str, str], ...] = (
    {
        "order_id": "LK202609070001",
        "member_id": "member-1001",
        "product_name": "生椰拿铁",
        "status": "COMPLETED",
    },
    {
        "order_id": "LK202609070002",
        "member_id": "member-1001",
        "product_name": "美式咖啡",
        "status": "PAID",
    },
    {
        "order_id": "LK202609070003",
        "member_id": "member-2002",
        "product_name": "橙C美式",
        "status": "CANCELLED",
    },
)


@dataclass(frozen=True)
class ToolCall:
    """模型发起的一次工具调用，结构对齐常见 Function Calling 协议。"""

    id: str
    type: str
    function: dict[str, str]


@dataclass(frozen=True)
class ToolResult:
    """工具执行后的返回消息，必须使用原始 tool_call_id 关联调用。"""

    role: str
    tool_call_id: str
    content: str


def build_tool_call(tool_call_id: str, arguments: dict[str, str]) -> ToolCall:
    """构造一条 search_orders 工具调用，arguments 按协议编码为 JSON 字符串。"""
    return ToolCall(
        id=tool_call_id,
        type="function",
        function={
            "name": "search_orders",
            "arguments": json.dumps(arguments, ensure_ascii=False),
        },
    )


def execute_search_orders(tool_call: ToolCall) -> ToolResult:
    """执行模拟订单查询，并构造关联到原工具调用 ID 的结果。"""
    if tool_call.type != "function" or tool_call.function.get("name") != "search_orders":
        raise ValueError("仅支持 search_orders function 调用")

    arguments = json.loads(tool_call.function["arguments"])
    _validate_search_orders_input(arguments)
    matched_orders = [
        order
        for order in MOCK_ORDERS
        if order["member_id"] == arguments["member_id"]
        and (not arguments.get("order_id") or order["order_id"] == arguments["order_id"])
        and (not arguments.get("status") or order["status"] == arguments["status"])
    ]
    result_content = {"orders": matched_orders, "total": len(matched_orders)}
    return ToolResult(
        role="tool",
        tool_call_id=tool_call.id,
        content=json.dumps(result_content, ensure_ascii=False),
    )


def _validate_search_orders_input(arguments: Any) -> None:
    """校验练习所需的最小输入约束，避免模拟 handler 接受无效参数。"""
    if not isinstance(arguments, dict):
        raise ValueError("arguments 必须是对象")
    allowed_fields = set(SEARCH_ORDERS_INPUT_SCHEMA["properties"])
    unexpected_fields = set(arguments) - allowed_fields
    if unexpected_fields:
        raise ValueError(f"不支持的字段: {sorted(unexpected_fields)}")
    if not isinstance(arguments.get("member_id"), str) or not arguments["member_id"].strip():
        raise ValueError("member_id 为必填非空字符串")
    status = arguments.get("status")
    if status is not None and status not in SEARCH_ORDERS_INPUT_SCHEMA["properties"]["status"]["enum"]:
        raise ValueError("status 不在支持的枚举范围内")


def run_demo() -> tuple[dict[str, Any], list[ToolCall], list[ToolResult]]:
    """完成两次不同 ID 的模拟调用，并断言每条结果均回关联到原调用。"""
    tool_calls = [
        build_tool_call("call_search_orders_001", {"member_id": "member-1001"}),
        build_tool_call(
            "call_search_orders_002",
            {"member_id": "member-1001", "status": "PAID"},
        ),
    ]
    tool_results = [execute_search_orders(tool_call) for tool_call in tool_calls]

    for tool_call, tool_result in zip(tool_calls, tool_results):
        assert tool_result.tool_call_id == tool_call.id, "Tool Result 必须关联原 Tool Call ID"

    return SEARCH_ORDERS_TOOL, tool_calls, tool_results


def main() -> None:
    """打印练习的 Tool JSON、两条调用和两条结果，便于手动观察协议结构。"""
    tool, tool_calls, tool_results = run_demo()
    print("第 2 步：模型可见 Tool JSON")
    print(json.dumps(tool, ensure_ascii=False, indent=2))
    print("\n第 3 步：两条 Tool Call")
    print(json.dumps([asdict(item) for item in tool_calls], ensure_ascii=False, indent=2))
    print("\n第 4 步：两条 Tool Result（关联 ID 断言已通过）")
    print(json.dumps([asdict(item) for item in tool_results], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
