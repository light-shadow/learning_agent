"""Agent Runtime 的 HTTP 与工具数据契约。"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TicketPriority(str, Enum):
    """工单优先级枚举。"""

    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class CreateTicketInput(BaseModel):
    """创建工单工具所需的最小输入。"""

    model_config = ConfigDict(extra="forbid")

    reporter_id: str = Field(min_length=1, max_length=64, description="提交工单的用户标识")
    title: str = Field(min_length=1, max_length=80, description="工单标题")
    description: str = Field(min_length=1, max_length=1000, description="问题详细描述")
    category: str = Field(min_length=1, max_length=32, description="问题分类")
    priority: TicketPriority = Field(description="工单优先级")


class Ticket(BaseModel):
    """内部工单系统返回的工单记录。"""

    ticket_id: str
    reporter_id: str
    title: str
    description: str
    category: str
    priority: TicketPriority
    status: Literal["open"]
    created_at: datetime


class ToolCallResult(BaseModel):
    """一次工具调用的可审计结果。"""

    tool_name: str
    input: dict[str, Any]
    status: Literal["success", "failed"]
    output: dict[str, Any] | None = None
    error: str | None = None


class AgentRunRequest(BaseModel):
    """提交给 Agent Runtime 的离线任务请求。"""

    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, max_length=64, description="发起任务的用户标识")
    message: str = Field(min_length=1, max_length=1000, description="用户描述的问题")

    @field_validator("user_id", "message")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        """拒绝只包含空白字符的用户标识和问题描述。"""
        if not value.strip():
            raise ValueError("不能为空或全为空白字符")
        return value


class AgentRunResponse(BaseModel):
    """Agent Runtime 执行后的统一响应。"""

    run_id: str
    status: Literal["completed", "failed"]
    output: str
    tool_calls: list[ToolCallResult]
