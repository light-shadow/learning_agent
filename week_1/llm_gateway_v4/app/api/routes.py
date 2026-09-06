"""v3 兼容接口和 v4 管理/Responses API 路由。"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.errors import GatewayError
from app.core.security import authenticate
from app.schemas import ChatRequest, ChatResponse, LLMRequest, LLMResponse, PromptCreate, PromptRender, ResponsesRequest, Usage
from app.services.prompts import apply_legacy_template, get_legacy_template
from app.services.structured import content_from_response, validate_response
from app.services.usage import usage_from_payload

router = APIRouter()
Identity = Annotated[str, Depends(authenticate)]


async def _limit(request: Request, identity: str, model: str) -> None:
    """同时校验调用方与逻辑模型的限流额度。"""
    await request.app.state.identity_limiter.check(identity)
    model_config = request.app.state.config.models.get(model)
    if model_config is None:
        raise GatewayError("模型别名不存在", status_code=404, code="model_not_found", error_type="invalid_request_error")
    await request.app.state.model_limiter.check(model, model_config.rate_limit)


@router.post("/v1/chat/completions")
async def chat_completions(payload: ChatRequest, request: Request, identity: Identity):
    """保持 v3 简化版 Chat 接口和 SSE 事件格式。"""
    await _limit(request, identity, payload.model)
    messages = payload.messages
    if payload.template:
        messages = apply_legacy_template(messages, payload.template)
    body, prompt_meta = request.app.state.gateway.prepare_chat({"model": payload.model, "messages": [item.model_dump() for item in messages], "response_format": payload.response_format.model_dump(by_alias=True) if payload.response_format else None, "temperature": payload.temperature, "max_tokens": payload.max_tokens, "timeout_seconds": payload.timeout_seconds}, payload.prompt, payload.gateway_prompt)
    if payload.stream:
        if payload.response_format:
            raise GatewayError("流式输出不支持结构化输出", status_code=400, code="unsupported_combination", error_type="invalid_request_error")
        iterator, request_id = await request.app.state.gateway.stream("chat", body, identity, "/v1/chat/completions", prompt_meta, request, "chat")
        return StreamingResponse(iterator, media_type="text/event-stream", headers={"X-Request-ID": request_id, "Cache-Control": "no-cache"})
    result, event = await request.app.state.gateway.call_json("chat", body, identity, "/v1/chat/completions", prompt_meta)
    content = content_from_response("chat", result)
    input_tokens, output_tokens, _ = usage_from_payload(result)
    return JSONResponse(ChatResponse(id=event["request_id"], model=event["upstream_model"] or payload.model, content=content, usage={"prompt_tokens": input_tokens, "completion_tokens": output_tokens, "total_tokens": input_tokens + output_tokens}, latency_ms=event["latency_ms"]).model_dump(), headers={"X-Request-ID": event["request_id"]})


@router.post("/v1/llm", response_model=LLMResponse)
async def llm(payload: LLMRequest, request: Request, identity: Identity) -> LLMResponse:
    """保持 v3 统一非流式 LLM 接口。"""
    if payload.stream:
        raise GatewayError("流式请求请使用 /v1/llm/stream", status_code=400, code="use_stream_endpoint", error_type="invalid_request_error")
    await _limit(request, identity, payload.model)
    body, prompt_meta = request.app.state.gateway.prepare_chat({"model": payload.model, "messages": [item.model_dump() for item in payload.messages], "response_schema": payload.response_schema, "temperature": payload.temperature, "max_tokens": payload.max_tokens, "timeout_seconds": payload.timeout_seconds}, payload.prompt, payload.gateway_prompt)
    body["response_schema"] = payload.response_schema
    result, event = await request.app.state.gateway.call_json("llm", body, identity, "/v1/llm", prompt_meta)
    parsed = validate_response("llm", result, payload.response_schema)
    content = content_from_response("llm", result)
    input_tokens, output_tokens, _ = usage_from_payload(result)
    return LLMResponse(request_id=event["request_id"], model=event["upstream_model"] or payload.model, content=content, parsed=parsed, usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens), latency_ms=int(event["latency_ms"]), attempts=event["retries"] + event["fallbacks"] + 1)


@router.post("/v1/llm/stream")
async def llm_stream(payload: LLMRequest, request: Request, identity: Identity):
    """保持 v3 新式 SSE 事件格式。"""
    if payload.response_schema is not None:
        raise GatewayError("流式输出不支持 response_schema", status_code=400, code="unsupported_combination", error_type="invalid_request_error")
    await _limit(request, identity, payload.model)
    body, prompt_meta = request.app.state.gateway.prepare_chat({"model": payload.model, "messages": [item.model_dump() for item in payload.messages], "temperature": payload.temperature, "max_tokens": payload.max_tokens, "timeout_seconds": payload.timeout_seconds}, payload.prompt, payload.gateway_prompt)
    iterator, request_id = await request.app.state.gateway.stream("llm", body, identity, "/v1/llm/stream", prompt_meta, request, "llm")
    return StreamingResponse(iterator, media_type="text/event-stream", headers={"X-Request-ID": request_id, "Cache-Control": "no-cache"})


@router.post("/v1/responses")
async def responses(payload: ResponsesRequest, request: Request, identity: Identity):
    """提供透明的 OpenAI Responses API 代理，仅路由至支持该协议的上游。"""
    await _limit(request, identity, payload.model)
    body, prompt_meta = request.app.state.gateway.prepare_responses(payload.model_dump(exclude_none=True), payload.gateway_prompt)
    if payload.stream:
        iterator, request_id = await request.app.state.gateway.stream("responses", body, identity, "/v1/responses", prompt_meta, request, "responses")
        return StreamingResponse(iterator, media_type="text/event-stream", headers={"X-Request-ID": request_id, "Cache-Control": "no-cache"})
    result, event = await request.app.state.gateway.call_json("responses", body, identity, "/v1/responses", prompt_meta)
    return JSONResponse(result, headers={"X-Request-ID": event["request_id"]})


@router.get("/v1/models")
async def models(request: Request, identity: Identity):
    """返回当前配置中允许调用的逻辑模型别名。"""
    await request.app.state.identity_limiter.check(identity)
    return {"object": "list", "data": [{"id": name, "object": "model", "owned_by": request.app.state.config.service_name} for name in sorted(request.app.state.config.models)]}


@router.post("/v1/prompts", status_code=201)
async def create_prompt(payload: PromptCreate, request: Request, identity: Identity):
    """发布一个持久化 Prompt 的新版本。"""
    await request.app.state.identity_limiter.check(identity)
    return request.app.state.prompts.create_version(payload)


@router.get("/v1/prompts")
async def list_prompts(request: Request, identity: Identity):
    """查询所有持久化 Prompt 版本。"""
    await request.app.state.identity_limiter.check(identity)
    return request.app.state.prompts.list()


@router.get("/v1/prompts/{prompt_id}")
async def get_prompt(prompt_id: str, request: Request, identity: Identity, version: int | None = None):
    """查询指定 Prompt 的激活版本或明确版本。"""
    await request.app.state.identity_limiter.check(identity)
    return request.app.state.prompts.get(prompt_id, version)


@router.post("/v1/prompts/{prompt_id}/render")
async def render_prompt(prompt_id: str, payload: PromptRender, request: Request, identity: Identity):
    """渲染持久化 Prompt，供调用前预览。"""
    await request.app.state.identity_limiter.check(identity)
    prompt, content = request.app.state.prompts.render(prompt_id, payload.variables, payload.version)
    return {"id": prompt["id"], "version": prompt["version"], "role": prompt["role"], "content": content}


@router.get("/v1/templates/{template_id}")
async def get_template(template_id: str, request: Request, identity: Identity, version: str | None = None):
    """保持 v3 静态模板读取接口。"""
    await request.app.state.identity_limiter.check(identity)
    template = get_legacy_template(template_id, version)
    if template is None:
        raise GatewayError("模板不存在", status_code=404, code="unknown_template", error_type="invalid_request_error")
    return template


@router.get("/v1/traces")
async def traces(request: Request, identity: Identity, limit: int = Query(default=100, ge=1, le=1000)):
    """保留 v3 审计查询入口，数据改为读取 SQLite。"""
    await request.app.state.identity_limiter.check(identity)
    return request.app.state.usage.recent(limit)


@router.get("/admin/usage")
async def usage(request: Request, identity: Identity, limit: int = Query(default=100, ge=1, le=1000)):
    """提供管理员审计查询入口。"""
    await request.app.state.identity_limiter.check(identity)
    return {"data": request.app.state.usage.recent(limit)}


@router.get("/admin/routes")
async def routes(request: Request, identity: Identity):
    """查看逻辑模型路由和当前供应商熔断状态。"""
    await request.app.state.identity_limiter.check(identity)
    return {"models": {name: config.model_dump(mode="json") for name, config in request.app.state.config.models.items()}, "circuits": request.app.state.router.status()}


@router.get("/v1/streams/{request_id}/checkpoint")
async def checkpoint(request_id: str, request: Request, identity: Identity):
    """查询已启用的流式正文检查点。"""
    await request.app.state.identity_limiter.check(identity)
    item = request.app.state.usage.get_checkpoint(request_id)
    if item is None:
        raise GatewayError("流式检查点不存在", status_code=404, code="checkpoint_not_found", error_type="invalid_request_error")
    return item


@router.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    """返回存活探针状态。"""
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
async def readyz(request: Request) -> dict[str, str]:
    """返回服务就绪探针状态。"""
    return {"status": "ready", "service": request.app.state.config.service_name}
