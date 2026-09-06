"""网关对外协议和内部标准数据模型。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Message(BaseModel):
    """表示跨供应商通用的一条聊天消息。"""

    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=20_000)


class TemplateReference(BaseModel):
    """兼容 v2 的用户消息模板选择参数。"""

    model_config = ConfigDict(extra="forbid")
    template_id: str = Field(min_length=1, max_length=100)
    version: str = Field(default="latest", min_length=1, max_length=50)
    variables: dict[str, str] = Field(default_factory=dict)


class PromptSelection(BaseModel):
    """表示受控系统 Prompt 的名称、版本和渲染变量。"""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=50)
    variables: dict[str, str] = Field(default_factory=dict)


class ResponseFormat(BaseModel):
    """兼容 v2 的结构化输出描述。"""

    model_config = ConfigDict(extra="forbid")
    type: Literal["json_object", "json_schema"]
    schema_: dict[str, Any] | None = Field(default=None, alias="schema")

    @model_validator(mode="after")
    def validate_schema(self) -> "ResponseFormat":
        """校验 json_schema 模式必须同时提供 JSON Schema。"""
        if self.type == "json_schema" and self.schema_ is None:
            raise ValueError("response_format.type=json_schema 时必须提供 schema")
        return self


class ChatRequest(BaseModel):
    """保留 v2 /v1/chat/completions 的请求协议。"""

    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1, max_length=100)
    messages: list[Message] = Field(min_length=1, max_length=100)
    stream: bool = False
    response_format: ResponseFormat | None = None
    template: TemplateReference | None = None
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=4096, gt=0, le=32_000)
    timeout_seconds: float = Field(default=30, gt=0, le=120)


class LLMRequest(BaseModel):
    """新 /v1/llm 协议的严格请求模型。"""

    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1, max_length=100)
    messages: list[Message] = Field(min_length=1, max_length=100)
    stream: bool = False
    response_schema: dict[str, Any] | None = None
    timeout_seconds: float = Field(default=30, gt=0, le=120)
    prompt: PromptSelection | None = None
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=4096, gt=0, le=32_000)

    @model_validator(mode="after")
    def validate_combination(self) -> "LLMRequest":
        """禁止在同一请求中混用流式输出和结构化输出。"""
        if self.stream and self.response_schema is not None:
            raise ValueError("stream 与 response_schema 不能同时使用")
        return self


class Usage(BaseModel):
    """统一输入、输出及总 Token 的统计口径。"""

    model_config = ConfigDict(extra="forbid")
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)

    @property
    def total_tokens(self) -> int:
        """返回本次调用的输入和输出 Token 总数。"""
        return self.input_tokens + self.output_tokens


class ChatResponse(BaseModel):
    """兼容 v2 非流式响应的输出结构。"""

    model_config = ConfigDict(extra="forbid")
    id: str
    model: str
    content: str
    usage: dict[str, int]
    reasoning: str | None = None
    latency_ms: float = Field(ge=0)
    first_token_latency_ms: float | None = None


class LLMResponse(BaseModel):
    """新接口的统一非流式响应结构。"""

    model_config = ConfigDict(extra="forbid")
    request_id: str
    model: str
    content: str
    parsed: dict[str, Any] | list[Any] | None = None
    usage: Usage
    latency_ms: int = Field(ge=0)
    attempts: int = Field(ge=1)


class CallTrace(BaseModel):
    """记录调用元数据，刻意不保存 Prompt 与模型响应正文。"""

    model_config = ConfigDict(extra="forbid")
    request_id: str
    timestamp: datetime
    requested_model: str
    actual_model: str | None = None
    prompt_name: str | None = None
    prompt_version: str | None = None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0)
    latency_ms: int = Field(ge=0)
    attempts: int = Field(ge=0)
    status: Literal["success", "failed"]
    error_code: str | None = None


class InternalRequest(BaseModel):
    """屏蔽双接口差异后的内部模型调用参数。"""

    model_config = ConfigDict(extra="forbid")
    model: str
    messages: list[Message]
    response_schema: dict[str, Any] | None = None
    timeout_seconds: float
    temperature: float
    max_tokens: int
    prompt: PromptSelection | None = None
