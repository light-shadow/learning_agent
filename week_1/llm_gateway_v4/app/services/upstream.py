"""OpenAI-compatible 与 Anthropic 上游 HTTP 调用封装。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import GatewayConfig, ProviderConfig
from app.core.errors import UpstreamError


@dataclass
class OpenStream:
    """封装已成功建立的上游流式 HTTP 响应。"""

    response: httpx.Response
    provider_name: str


class UpstreamClient:
    """按供应商协议发送请求，并将失败统一转换为可重试错误。"""

    def __init__(self, config: GatewayConfig, client: httpx.AsyncClient | None = None) -> None:
        self.config = config
        self.client = client or httpx.AsyncClient()
        self._owns_client = client is None

    async def close(self) -> None:
        """关闭由网关创建的共享 HTTP 客户端。"""
        if self._owns_client:
            await self.client.aclose()

    async def request_json(self, provider_name: str, api: str, body: dict[str, Any], request_id: str) -> dict[str, Any]:
        """调用非流式上游接口并返回统一 Chat 或透明 Responses JSON。"""
        provider = self.config.providers[provider_name]
        path, upstream_body = self._request_parts(provider, api, body)
        try:
            response = await self.client.post(f"{provider.base_url}{path}", headers=self._headers(provider, request_id), json=upstream_body, timeout=self._timeout(provider))
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise UpstreamError(f"{provider_name}: {type(exc).__name__}", retryable=True) from exc
        if response.is_error:
            raise self._http_error(provider_name, response)
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise UpstreamError(f"{provider_name}: 上游返回非法 JSON") from exc
        return self._anthropic_to_chat(payload) if provider.protocol == "anthropic" else payload

    async def open_stream(self, provider_name: str, api: str, body: dict[str, Any], request_id: str) -> OpenStream:
        """建立上游 SSE 连接，调用方负责在结束后关闭响应。"""
        provider = self.config.providers[provider_name]
        path, upstream_body = self._request_parts(provider, api, body)
        request = self.client.build_request("POST", f"{provider.base_url}{path}", headers={**self._headers(provider, request_id), "Accept": "text/event-stream"}, json=upstream_body)
        try:
            response = await self.client.send(request, stream=True)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise UpstreamError(f"{provider_name}: {type(exc).__name__}", retryable=True) from exc
        if response.is_error:
            await response.aread()
            error = self._http_error(provider_name, response)
            await response.aclose()
            raise error
        return OpenStream(response=response, provider_name=provider_name)

    def _request_parts(self, provider: ProviderConfig, api: str, body: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        if provider.protocol != "anthropic":
            return ("/v1/chat/completions" if api in ("chat", "llm") else "/v1/responses"), body
        if api == "responses":
            raise UpstreamError("Anthropic 不支持 Responses API", status_code=400)
        messages = list(body.get("messages", []))
        system = "\n\n".join(str(message["content"]) for message in messages if message.get("role") == "system") or None
        payload = {"model": body["model"], "messages": [{"role": item["role"], "content": item["content"]} for item in messages if item.get("role") != "system"], "max_tokens": body.get("max_tokens", 4096), "temperature": body.get("temperature", 0.7), "stream": body.get("stream", False)}
        if system:
            payload["system"] = system
        return "/v1/messages", payload

    @staticmethod
    def _anthropic_to_chat(payload: dict[str, Any]) -> dict[str, Any]:
        content = "".join(str(block.get("text", "")) for block in payload.get("content", []) if block.get("type") == "text")
        usage = payload.get("usage") or {}
        return {"id": payload.get("id"), "model": payload.get("model"), "choices": [{"message": {"role": "assistant", "content": content}}], "usage": {"prompt_tokens": usage.get("input_tokens", 0), "completion_tokens": usage.get("output_tokens", 0)}}

    @staticmethod
    def _headers(provider: ProviderConfig, request_id: str) -> dict[str, str]:
        api_key = provider.api_key.get_secret_value()
        headers = {"X-Request-ID": request_id, **provider.extra_headers}
        if provider.protocol == "anthropic":
            headers.update({"x-api-key": api_key, "anthropic-version": "2023-06-01"})
        elif api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    @staticmethod
    def _timeout(provider: ProviderConfig) -> httpx.Timeout:
        return httpx.Timeout(provider.timeout_seconds, connect=provider.connect_timeout_seconds)

    def _http_error(self, provider_name: str, response: httpx.Response) -> UpstreamError:
        status = response.status_code
        details: Any
        try:
            details = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            details = response.text[:1000]
        retryable = status in self.config.retry.retry_statuses
        public_status = status if 400 <= status < 500 else 502
        return UpstreamError(f"{provider_name}: HTTP {status}", status_code=public_status, retryable=retryable, details=details)
