"""兼容 v2 与参考 Gateway 协议的 LLM Gateway v3。"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from jsonschema import ValidationError as JsonSchemaError
from jsonschema import validate

from adapters.anthropic_adapter import AnthropicAdapter
from adapters.base import BaseAdapter
from adapters.openai_compatible import OpenAICompatibleAdapter
from config import MAX_ATTEMPTS_PER_MODEL, MODEL_CONFIGS, ModelConfig
from errors import GatewayError
from models import ChatRequest, ChatResponse, InternalRequest, LLMRequest, LLMResponse, Message, PromptSelection, Usage
from observability import trace_store
from resilience import RateLimiter, is_retryable
from templates import apply_legacy_template, get_legacy_template, render_prompt

logger = logging.getLogger("llm_gateway_v3")
app = FastAPI(title="LLM Gateway v3", version="3.0.0")
rate_limiter = RateLimiter({name: config.rate_limit_per_minute for name, config in MODEL_CONFIGS.items()})


def get_adapter(config: ModelConfig) -> BaseAdapter:
    """根据供应商类型返回对应适配器，避免业务流程依赖 SDK 细节。"""
    if config.provider in ("deepseek", "openai"):
        return OpenAICompatibleAdapter()
    if config.provider == "anthropic":
        return AnthropicAdapter()
    raise GatewayError("gateway_misconfigured", "模型供应商配置无效", 503)


def validate_model(model: str, response_schema: dict[str, Any] | None) -> ModelConfig:
    """校验逻辑模型白名单与结构化输出能力。"""
    config = MODEL_CONFIGS.get(model)
    if config is None:
        raise GatewayError("unknown_model", "模型不在 Gateway 允许列表中", 400)
    if response_schema is not None and not config.supports_structured_output:
        raise GatewayError("structured_output_unsupported", "模型不支持 Structured Output", 400)
    return config


def build_messages(request: InternalRequest) -> list[Message]:
    """将受控系统 Prompt 注入到请求消息的最前方。"""
    if request.prompt is None:
        return request.messages
    return [render_prompt(request.prompt), *request.messages]


def encode_sse(event: dict[str, Any]) -> str:
    """将统一事件编码为 SSE 数据帧。"""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


async def complete_with_fallback(
    request: InternalRequest,
    request_id: str | None = None,
    trace_prompt: PromptSelection | None = None,
) -> tuple[str, Usage, str | None, str, str, int, int]:
    """执行非流式调用，在可重试故障后按配置切换一次备用模型。"""
    requested_model = request.model
    started = time.perf_counter()
    attempts = 0
    last_error: Exception | None = None
    primary = validate_model(request.model, request.response_schema)
    model_names = [requested_model]
    if primary.fallback_model and primary.fallback_model != requested_model:
        model_names.append(primary.fallback_model)

    rendered_request = request.model_copy(update={"messages": build_messages(request)})
    for model_name in model_names:
        config = validate_model(model_name, request.response_schema)
        for retry_number in range(MAX_ATTEMPTS_PER_MODEL):
            attempts += 1
            try:
                content, usage, reasoning = await get_adapter(config).complete(config, rendered_request)
                latency_ms = int((time.perf_counter() - started) * 1000)
                return content, usage, reasoning, requested_model, model_name, attempts, latency_ms
            except GatewayError:
                raise
            except Exception as exc:
                last_error = exc
                if not is_retryable(exc):
                    latency_ms = int((time.perf_counter() - started) * 1000)
                    trace_store.record(request_id or str(uuid4()), requested_model, None, trace_prompt or request.prompt, Usage(input_tokens=0, output_tokens=0), latency_ms, attempts, "failed", "upstream_request_failed")
                    raise GatewayError("upstream_request_failed", "上游模型调用失败") from exc
                if is_retryable(exc) and retry_number < MAX_ATTEMPTS_PER_MODEL - 1:
                    await asyncio.sleep(0.1 * (retry_number + 1))
                    continue
                break
    latency_ms = int((time.perf_counter() - started) * 1000)
    trace_store.record(request_id or str(uuid4()), requested_model, None, trace_prompt or request.prompt, Usage(input_tokens=0, output_tokens=0), latency_ms, attempts, "failed", "model_unavailable")
    raise GatewayError("model_unavailable", "主模型和备用模型均不可用") from last_error


async def stream_with_fallback(request: InternalRequest) -> AsyncIterator[tuple[str, dict[str, str] | None, int, str | None]]:
    """流首块前可切备用模型，首块后异常只返回失败状态以避免内容重复。"""
    primary = validate_model(request.model, None)
    model_names = [request.model]
    if primary.fallback_model and primary.fallback_model != request.model:
        model_names.append(primary.fallback_model)
    rendered_request = request.model_copy(update={"messages": build_messages(request)})
    attempts = 0
    emitted = False
    started = time.perf_counter()
    stream_request_id = str(uuid4())
    for model_name in model_names:
        config = validate_model(model_name, None)
        for retry_number in range(MAX_ATTEMPTS_PER_MODEL):
            attempts += 1
            try:
                async for event in get_adapter(config).stream(config, rendered_request):
                    emitted = True
                    yield "event", event, attempts, model_name
                latency_ms = int((time.perf_counter() - started) * 1000)
                trace_store.record(stream_request_id, request.model, model_name, request.prompt, Usage(input_tokens=0, output_tokens=0), latency_ms, attempts, "success")
                yield "completed", None, attempts, model_name
                return
            except GatewayError as exc:
                if emitted:
                    yield "failed", {"error": exc.code}, attempts, model_name
                    return
                latency_ms = int((time.perf_counter() - started) * 1000)
                trace_store.record(stream_request_id, request.model, None, request.prompt, Usage(input_tokens=0, output_tokens=0), latency_ms, attempts, "failed", exc.code)
                yield "failed", {"error": exc.code}, attempts, model_name
                return
            except Exception as exc:
                if emitted or not is_retryable(exc):
                    logger.warning("上游流式调用失败: %s", type(exc).__name__)
                    latency_ms = int((time.perf_counter() - started) * 1000)
                    trace_store.record(stream_request_id, request.model, None, request.prompt, Usage(input_tokens=0, output_tokens=0), latency_ms, attempts, "failed", "upstream_stream_failed")
                    yield "failed", {"error": "upstream_stream_failed"}, attempts, model_name
                    return
                if retry_number < MAX_ATTEMPTS_PER_MODEL - 1:
                    await asyncio.sleep(0.1 * (retry_number + 1))
                    continue
                break
    latency_ms = int((time.perf_counter() - started) * 1000)
    trace_store.record(stream_request_id, request.model, None, request.prompt, Usage(input_tokens=0, output_tokens=0), latency_ms, attempts, "failed", "upstream_stream_failed")
    yield "failed", {"error": "upstream_stream_failed"}, attempts, None


def ensure_rate_limit(model: str) -> None:
    """检查入口请求的模型限流额度，并在超限时立即拒绝。"""
    validate_model(model, None)
    if not rate_limiter.allow_request(model):
        raise GatewayError("rate_limit_exceeded", "模型请求频率超限", 429)


def to_internal_request(request: ChatRequest) -> InternalRequest:
    """将 v2 兼容请求映射为统一内部请求。"""
    messages = request.messages
    if request.template is not None:
        messages = apply_legacy_template(messages, request.template)
    schema = request.response_format.schema_ if request.response_format and request.response_format.type == "json_schema" else None
    if request.response_format and request.response_format.type == "json_object":
        schema = {"type": "object"}
    return InternalRequest(
        model=request.model,
        messages=messages,
        response_schema=schema,
        timeout_seconds=request.timeout_seconds,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
    )


def to_internal_llm_request(request: LLMRequest) -> InternalRequest:
    """将新接口请求映射为统一内部请求。"""
    return InternalRequest(
        model=request.model,
        messages=request.messages,
        response_schema=request.response_schema,
        timeout_seconds=request.timeout_seconds,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        prompt=request.prompt,
    )


def validate_structured_response(content: str, schema: dict[str, Any] | None) -> dict[str, Any] | list[Any] | None:
    """解析并校验模型返回的结构化 JSON。"""
    if schema is None:
        return None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise GatewayError("invalid_json", "模型没有返回合法 JSON") from exc
    try:
        validate(instance=parsed, schema=schema)
    except JsonSchemaError as exc:
        raise GatewayError("schema_validation_failed", "模型结果不符合 response_schema") from exc
    if not isinstance(parsed, (dict, list)):
        raise GatewayError("schema_validation_failed", "结构化输出必须是对象或数组")
    return parsed


@app.post("/v1/chat/completions")
async def chat_completion(request: ChatRequest):
    """提供向后兼容的 v2 聊天补全入口。"""
    try:
        ensure_rate_limit(request.model)
        internal_request = to_internal_request(request)
        if request.stream:
            if internal_request.response_schema is not None:
                raise GatewayError("unsupported_combination", "流式输出不支持结构化输出", 400)

            async def legacy_events() -> AsyncIterator[str]:
                async for state, event, _, _ in stream_with_fallback(internal_request):
                    if state == "event" and event:
                        yield encode_sse(event)
                    elif state == "failed" and event:
                        yield encode_sse({"type": "error", **event})
                yield "data: [DONE]\n\n"

            return StreamingResponse(legacy_events(), media_type="text/event-stream")
        request_id = str(uuid4())
        legacy_trace_prompt = PromptSelection(name=request.template.template_id, version=request.template.version) if request.template else None
        content, usage, reasoning, requested_model, actual_model, attempts, latency_ms = await complete_with_fallback(internal_request, request_id, legacy_trace_prompt)
        try:
            validate_structured_response(content, internal_request.response_schema)
        except GatewayError as exc:
            trace_store.record(request_id, requested_model, actual_model, legacy_trace_prompt, usage, latency_ms, attempts, "failed", exc.code)
            raise
        trace_store.record(request_id, requested_model, actual_model, legacy_trace_prompt, usage, latency_ms, attempts, "success")
        return ChatResponse(
            id=request_id,
            model=actual_model,
            content=content,
            usage={"prompt_tokens": usage.input_tokens, "completion_tokens": usage.output_tokens, "total_tokens": usage.total_tokens},
            reasoning=reasoning,
            latency_ms=latency_ms,
        )
    except GatewayError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc


@app.post("/v1/llm", response_model=LLMResponse)
async def create_llm_response(request: LLMRequest) -> LLMResponse:
    """提供参考实现风格的统一非流式模型调用入口。"""
    if request.stream:
        raise HTTPException(status_code=400, detail={"code": "use_stream_endpoint", "message": "流式请求请使用 /v1/llm/stream"})
    request_id = str(uuid4())
    try:
        ensure_rate_limit(request.model)
        internal_request = to_internal_llm_request(request)
        content, usage, _, requested_model, actual_model, attempts, latency_ms = await complete_with_fallback(internal_request, request_id)
        try:
            parsed = validate_structured_response(content, internal_request.response_schema)
        except GatewayError as exc:
            trace_store.record(request_id, requested_model, actual_model, request.prompt, usage, latency_ms, attempts, "failed", exc.code)
            raise
        trace_store.record(request_id, requested_model, actual_model, request.prompt, usage, latency_ms, attempts, "success")
        return LLMResponse(request_id=request_id, model=actual_model, content=content, parsed=parsed, usage=usage, latency_ms=latency_ms, attempts=attempts)
    except GatewayError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc


@app.post("/v1/llm/stream")
async def create_stream(request: LLMRequest) -> StreamingResponse:
    """提供新协议的 SSE 流式输出入口。"""
    if request.response_schema is not None:
        raise HTTPException(status_code=400, detail={"code": "unsupported_combination", "message": "流式输出不支持 response_schema"})
    try:
        ensure_rate_limit(request.model)
        internal_request = to_internal_llm_request(request)
        build_messages(internal_request)
    except GatewayError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc

    async def new_events() -> AsyncIterator[str]:
        async for state, event, _, model_name in stream_with_fallback(internal_request):
            if state == "event" and event:
                if event["type"] == "content":
                    yield encode_sse({"type": "content.delta", "delta": event["content"]})
                else:
                    yield encode_sse({"type": "reasoning.delta", "delta": event["content"]})
            elif state == "completed":
                yield encode_sse({"type": "response.completed", "model": model_name})
            elif state == "failed" and event:
                yield encode_sse({"type": "response.failed", **event})

    return StreamingResponse(new_events(), media_type="text/event-stream")


@app.get("/v1/traces")
async def list_traces():
    """查询不含业务正文的调用审计记录。"""
    return trace_store.list_records()


@app.get("/v1/templates/{template_id}")
async def get_template(template_id: str, version: str | None = None):
    """读取受控的 v2 兼容模板，不提供调用方写入入口。"""
    template = get_legacy_template(template_id, version)
    if template is None:
        raise HTTPException(status_code=404, detail={"code": "unknown_template", "message": "模板不存在"})
    return template
