"""调用编排：路由、重试、结构化修复、流式转发和审计。"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from fastapi import Request

from app.config import GatewayConfig, RouteTarget
from app.core.errors import GatewayError, UpstreamError, error_payload
from app.schemas import GatewayPromptReference, Message, PromptSelection
from app.services.prompts import PromptRepository, apply_static_prompt
from app.services.router import ModelRouter
from app.services.structured import content_from_response, extract_schema, repair_instruction, validate_response
from app.services.upstream import UpstreamClient
from app.services.usage import UsageRepository, usage_from_payload

logger = logging.getLogger("llm_gateway_v4.gateway")


class GatewayService:
    """集中执行所有 API 的上游调用、可靠性策略和审计记录。"""

    def __init__(self, config: GatewayConfig, router: ModelRouter, upstream: UpstreamClient, prompts: PromptRepository, usage: UsageRepository) -> None:
        self.config = config
        self.router = router
        self.upstream = upstream
        self.prompts = prompts
        self.usage = usage

    def prepare_chat(self, body: dict[str, Any], static_prompt: PromptSelection | None, persistent_prompt: GatewayPromptReference | None) -> tuple[dict[str, Any], tuple[str | None, int | None]]:
        """对 Chat 请求注入 v3 静态 Prompt 或持久化 Gateway Prompt。"""
        copied = dict(body)
        messages = [Message.model_validate(item) for item in copied.get("messages", [])]
        messages = apply_static_prompt(messages, static_prompt)
        prompt_meta: tuple[str | None, int | None] = (None, None)
        if persistent_prompt:
            prompt, rendered = self.prompts.render(persistent_prompt.id, persistent_prompt.variables, persistent_prompt.version)
            item = Message(role="system" if prompt["role"] == "system" else "system", content=rendered)
            messages = [item, *messages] if persistent_prompt.position == "prepend" else [*messages, item]
            prompt_meta = (prompt["id"], prompt["version"])
        copied["messages"] = [item.model_dump() for item in messages]
        copied.pop("prompt", None)
        copied.pop("gateway_prompt", None)
        copied.pop("response_schema", None)
        return copied, prompt_meta

    def prepare_responses(self, body: dict[str, Any], persistent_prompt: GatewayPromptReference | None) -> tuple[dict[str, Any], tuple[str | None, int | None]]:
        """为 Responses 请求注入持久化 Prompt 到 instructions 字段。"""
        copied = dict(body)
        copied.pop("gateway_prompt", None)
        if not persistent_prompt:
            return copied, (None, None)
        prompt, rendered = self.prompts.render(persistent_prompt.id, persistent_prompt.variables, persistent_prompt.version)
        existing = copied.get("instructions")
        copied["instructions"] = f"{rendered}\n\n{existing}" if existing else rendered
        return copied, (prompt["id"], prompt["version"])

    async def call_json(self, api: str, body: dict[str, Any], identity: str, endpoint: str, prompt_meta: tuple[str | None, int | None] = (None, None)) -> tuple[dict[str, Any], dict[str, Any]]:
        """执行非流式调用，处理多路由重试、结构化修复和 SQLite 审计。"""
        request_id, started = f"req_{uuid4().hex}", time.perf_counter()
        event = self._event(request_id, identity, endpoint, body["model"], False, prompt_meta)
        schema = extract_schema(api, body)
        working = dict(body)
        repair_count = 0
        try:
            while True:
                result, target = await self._call_routes(api, working, request_id, event)
                if schema is None:
                    return result, event
                try:
                    validate_response(api, result, schema)
                    return result, event
                except GatewayError as exc:
                    if repair_count >= self.config.structured_output_retries:
                        raise
                    repair_count += 1
                    event["retries"] += 1
                    working = self._append_repair(api, working, content_from_response(api, result), repair_instruction(exc, schema))
        except GatewayError as exc:
            event.update(status="error", status_code=exc.status_code, error_type=exc.error_type, error_message=exc.message)
            raise
        finally:
            event["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
            event["cost_usd"] = self.usage.calculate_cost(event["upstream_model"], event["input_tokens"], event["output_tokens"], event["cached_tokens"])
            self.usage.record(event)

    async def stream(self, api: str, body: dict[str, Any], identity: str, endpoint: str, prompt_meta: tuple[str | None, int | None], request: Request, output_mode: str) -> tuple[AsyncIterator[bytes], str]:
        """建立流式调用；首块前重试/fallback，首块后仅发送错误并终止。"""
        request_id = f"req_{uuid4().hex}"
        event = self._event(request_id, identity, endpoint, body["model"], True, prompt_meta)

        async def generate() -> AsyncIterator[bytes]:
            started, emitted, completed, text = time.perf_counter(), False, False, ""
            try:
                route_api = "chat" if api == "llm" else api
                for index, target in enumerate(self.router.candidates(body["model"], route_api)):
                    for attempt in range(self.config.retry.max_attempts_per_route):
                        opened = None
                        try:
                            upstream_body = {**body, "model": target.model, "stream": True}
                            opened = await self.upstream.open_stream(target.provider, api, upstream_body, request_id)
                            event.update(provider=target.provider, upstream_model=target.model, fallbacks=index)
                            buffer = ""
                            async for chunk in opened.response.aiter_bytes():
                                if await request.is_disconnected():
                                    event.update(status="cancelled", status_code=499)
                                    return
                                buffer += chunk.decode("utf-8", errors="ignore")
                                buffer, delta, usage = self._parse_sse(buffer)
                                if delta and not emitted:
                                    emitted = True
                                    event["first_token_ms"] = round((time.perf_counter() - started) * 1000, 3)
                                if usage:
                                    event["input_tokens"], event["output_tokens"], event["cached_tokens"] = usage
                                if delta:
                                    text = (text + delta)[-self.config.stream_checkpoint.max_chars:]
                                yield self._stream_chunk(chunk, delta, output_mode)
                            self.router.record_success(target.provider)
                            completed = True
                            if output_mode == "llm":
                                yield f"data: {json.dumps({'type': 'response.completed', 'model': target.model}, ensure_ascii=False)}\n\n".encode()
                            elif output_mode == "chat":
                                yield b"data: [DONE]\n\n"
                            return
                        except (UpstreamError, Exception) as exc:
                            error = exc if isinstance(exc, UpstreamError) else UpstreamError("上游流式连接中断", retryable=not emitted)
                            self.router.record_failure(target.provider)
                            if emitted or not error.retryable:
                                event.update(status="error", status_code=error.status_code, error_type=error.error_type, error_message=error.message)
                                yield self._error_sse(error, output_mode)
                                return
                            if attempt + 1 < self.config.retry.max_attempts_per_route:
                                event["retries"] += 1
                                await self._backoff(attempt)
                        finally:
                            if opened:
                                await opened.response.aclose()
                error = GatewayError("所有上游模型均不可用", status_code=502, code="model_unavailable", error_type="upstream_error")
                event.update(status="error", status_code=error.status_code, error_type=error.error_type, error_message=error.message)
                yield self._error_sse(error, output_mode)
            except GatewayError as error:
                event.update(status="error", status_code=error.status_code, error_type=error.error_type, error_message=error.message)
                logger.warning("stream_gateway_error request_id=%s code=%s message=%s", request_id, error.code, error.message)
                yield self._error_sse(error, output_mode)
            finally:
                if completed:
                    event.update(status="success", status_code=200)
                event["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
                event["cost_usd"] = self.usage.calculate_cost(event["upstream_model"], event["input_tokens"], event["output_tokens"], event["cached_tokens"])
                if self.config.stream_checkpoint.enabled:
                    self.usage.save_checkpoint(request_id, api, body["model"], event["status"], text)
                self.usage.record(event)

        return generate(), request_id

    async def _call_routes(self, api: str, body: dict[str, Any], request_id: str, event: dict[str, Any]) -> tuple[dict[str, Any], RouteTarget]:
        last_error: GatewayError | None = None
        route_api = "chat" if api == "llm" else api
        for index, target in enumerate(self.router.candidates(body["model"], route_api)):
            for attempt in range(self.config.retry.max_attempts_per_route):
                try:
                    upstream_body = {**body, "model": target.model, "stream": False}
                    if api == "llm":
                        upstream_body.pop("response_schema", None)
                        if body.get("response_schema"):
                            upstream_body["response_format"] = {"type": "json_object"}
                    result = await self.upstream.request_json(target.provider, api, upstream_body, request_id)
                    self.router.record_success(target.provider)
                    input_tokens, output_tokens, cached_tokens = usage_from_payload(result)
                    event.update(provider=target.provider, upstream_model=target.model, input_tokens=event["input_tokens"] + input_tokens, output_tokens=event["output_tokens"] + output_tokens, cached_tokens=event["cached_tokens"] + cached_tokens, fallbacks=index)
                    return result, target
                except UpstreamError as exc:
                    last_error = exc
                    self.router.record_failure(target.provider)
                    if not exc.retryable or attempt + 1 >= self.config.retry.max_attempts_per_route:
                        break
                    event["retries"] += 1
                    await self._backoff(attempt)
        raise last_error or GatewayError("所有上游模型均不可用", status_code=502, code="model_unavailable", error_type="upstream_error")

    @staticmethod
    def _event(request_id: str, identity: str, endpoint: str, model: str, stream: bool, prompt_meta: tuple[str | None, int | None]) -> dict[str, Any]:
        return {"request_id": request_id, "api_key_hash": identity, "endpoint": endpoint, "requested_model": model, "provider": None, "upstream_model": None, "stream": int(stream), "status": "success", "status_code": 200, "input_tokens": 0, "output_tokens": 0, "cached_tokens": 0, "cost_usd": 0.0, "latency_ms": 0.0, "first_token_ms": None, "retries": 0, "fallbacks": 0, "error_type": None, "error_message": None, "prompt_id": prompt_meta[0], "prompt_version": prompt_meta[1], "metadata_json": None}

    async def _backoff(self, attempt: int) -> None:
        delay = min(self.config.retry.base_delay_seconds * (2 ** attempt), self.config.retry.max_delay_seconds)
        await asyncio.sleep(delay * random.uniform(0.75, 1.25))

    @staticmethod
    def _append_repair(api: str, body: dict[str, Any], previous: str, instruction: str) -> dict[str, Any]:
        copied = dict(body)
        if api in ("chat", "llm"):
            copied["messages"] = [*body.get("messages", []), {"role": "assistant", "content": previous}, {"role": "user", "content": instruction}]
        else:
            original = body.get("input", "")
            copied["input"] = [*(original if isinstance(original, list) else [{"role": "user", "content": original}]), {"role": "assistant", "content": previous}, {"role": "user", "content": instruction}]
        return copied

    @staticmethod
    def _parse_sse(buffer: str) -> tuple[str, str, tuple[int, int, int] | None]:
        buffer = buffer.replace("\r\n", "\n")
        delta, usage = "", None
        while "\n\n" in buffer:
            raw, buffer = buffer.split("\n\n", 1)
            data = next((line[5:].strip() for line in raw.splitlines() if line.startswith("data:")), "")
            if not data or data == "[DONE]":
                continue
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                continue
            parsed_usage = usage_from_payload(payload.get("response", payload))
            if any(parsed_usage):
                usage = parsed_usage
            choices = payload.get("choices") or []
            if choices:
                delta += str((choices[0].get("delta") or {}).get("content") or "")
            if payload.get("type") == "response.output_text.delta":
                delta += str(payload.get("delta") or "")
            if payload.get("type") == "content_block_delta":
                delta += str((payload.get("delta") or {}).get("text") or "")
        return buffer[-65536:], delta, usage

    @staticmethod
    def _stream_chunk(raw: bytes, delta: str, mode: str) -> bytes:
        if mode == "responses":
            return raw
        if delta:
            payload = {"type": "content.delta", "delta": delta} if mode == "llm" else {"type": "content", "content": delta}
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()
        return b""

    @staticmethod
    def _error_sse(error: GatewayError, mode: str) -> bytes:
        if mode == "responses":
            return f"data: {json.dumps(error_payload(error), ensure_ascii=False)}\n\ndata: [DONE]\n\n".encode()
        if mode == "llm":
            return f"data: {json.dumps({'type': 'response.failed', 'error': error.code or 'upstream_stream_failed'}, ensure_ascii=False)}\n\n".encode()
        return f"data: {json.dumps({'type': 'error', **error_payload(error)['error']}, ensure_ascii=False)}\n\ndata: [DONE]\n\n".encode()
