"""v3 兼容协议与 v4 新增 API 的请求响应模型。"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Message(BaseModel):
    """表示 v3 兼容接口的一条聊天消息。"""

    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=20_000)


class TemplateReference(BaseModel):
    """表示 v3 静态用户模板引用。"""

    model_config = ConfigDict(extra="forbid")
    template_id: str
    version: str = "latest"
    variables: dict[str, str] = Field(default_factory=dict)


class PromptSelection(BaseModel):
    """表示 v3 静态系统 Prompt 引用。"""

    model_config = ConfigDict(extra="forbid")
    name: str
    version: str
    variables: dict[str, str] = Field(default_factory=dict)


class GatewayPromptReference(BaseModel):
    """表示 SQLite 持久化 Prompt 的版本与注入位置。"""

    model_config = ConfigDict(extra="forbid")
    id: str
    version: int | None = Field(default=None, ge=1)
    variables: dict[str, Any] = Field(default_factory=dict)
    position: Literal["prepend", "append"] = "prepend"


class ResponseFormat(BaseModel):
    """兼容 v3 的 json_object 与简化 json_schema 协议。"""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    type: Literal["json_object", "json_schema"]
    schema_: dict[str, Any] | None = Field(default=None, alias="schema")

    @model_validator(mode="after")
    def require_schema(self) -> "ResponseFormat":
        """要求简化 json_schema 结构提供 schema 字段。"""
        if self.type == "json_schema" and self.schema_ is None:
            raise ValueError("json_schema 模式必须提供 schema")
        return self


class ChatRequest(BaseModel):
    """保持 v3 简化版 Chat Completions 请求兼容。"""

    model_config = ConfigDict(extra="forbid")
    model: str
    messages: list[Message] = Field(min_length=1, max_length=100)
    stream: bool = False
    response_format: ResponseFormat | None = None
    template: TemplateReference | None = None
    prompt: PromptSelection | None = None
    gateway_prompt: GatewayPromptReference | None = None
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=4096, gt=0, le=32_000)
    timeout_seconds: float = Field(default=30, gt=0, le=120)


class LLMRequest(BaseModel):
    """保持 v3 /v1/llm 的请求协议，并增加持久化 Prompt 引用。"""

    model_config = ConfigDict(extra="forbid")
    model: str
    messages: list[Message] = Field(min_length=1, max_length=100)
    stream: bool = False
    response_schema: dict[str, Any] | None = None
    timeout_seconds: float = Field(default=30, gt=0, le=120)
    prompt: PromptSelection | None = None
    gateway_prompt: GatewayPromptReference | None = None
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=4096, gt=0, le=32_000)

    @model_validator(mode="after")
    def validate_combination(self) -> "LLMRequest":
        """禁止 v3 流式请求与结构化输出同时使用。"""
        if self.stream and self.response_schema is not None:
            raise ValueError("stream 与 response_schema 不能同时使用")
        return self


class ResponsesRequest(BaseModel):
    """定义新增 Responses API 的透传请求模型。"""

    model_config = ConfigDict(extra="allow")
    model: str
    input: Any
    stream: bool = False
    temperature: float | None = None
    max_output_tokens: int | None = Field(default=None, ge=1)
    text: dict[str, Any] | None = None
    gateway_prompt: GatewayPromptReference | None = None


class PromptCreate(BaseModel):
    """定义持久化 Prompt 的创建与发布参数。"""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")
    name: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    description: str | None = None
    role: Literal["system", "developer"] = "system"
    activate: bool = True


class PromptRender(BaseModel):
    """定义 Prompt 渲染的变量和目标版本。"""

    model_config = ConfigDict(extra="forbid")
    version: int | None = Field(default=None, ge=1)
    variables: dict[str, Any] = Field(default_factory=dict)


class Usage(BaseModel):
    """表示 v3 统一 Token 统计。"""

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class ChatResponse(BaseModel):
    """保持 v3 简化版非流式 Chat 响应格式。"""

    id: str
    model: str
    content: str
    usage: dict[str, int]
    reasoning: str | None = None
    latency_ms: float
    first_token_latency_ms: float | None = None


class LLMResponse(BaseModel):
    """保持 v3 /v1/llm 非流式响应格式。"""

    request_id: str
    model: str
    content: str
    parsed: dict[str, Any] | list[Any] | None = None
    usage: Usage
    latency_ms: int
    attempts: int
