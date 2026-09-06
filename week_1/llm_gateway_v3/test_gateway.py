"""使用 Fake Adapter 验证 v3 的离线核心行为。"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import httpx

import gateway
from config import MODEL_CONFIGS
from models import InternalRequest, Usage
from observability import TraceStore
from resilience import RateLimiter


class FakeAdapter:
    """模拟供应商调用，以避免离线测试访问真实模型服务。"""

    def __init__(self, content: str = "正常结果", failures: int = 0, stream_failure_after_first: bool = False) -> None:
        self.content = content
        self.failures = failures
        self.stream_failure_after_first = stream_failure_after_first
        self.calls: list[str] = []

    async def complete(self, config, request: InternalRequest):
        """按预设失败次数模拟非流式调用。"""
        self.calls.append(config.provider_model)
        if self.failures:
            self.failures -= 1
            raise TimeoutError("temporary upstream timeout")
        return self.content, Usage(input_tokens=11, output_tokens=7), None

    async def stream(self, config, request: InternalRequest) -> AsyncIterator[dict[str, str]]:
        """模拟内容增量和首块后的上游失败。"""
        self.calls.append(config.provider_model)
        yield {"type": "content", "content": "第一块"}
        if self.stream_failure_after_first:
            raise TimeoutError("stream interrupted")
        yield {"type": "content", "content": "第二块"}


async def request(path: str, payload: dict) -> httpx.Response:
    """通过 ASGITransport 调用应用，无需启动真实 HTTP 服务。"""
    transport = httpx.ASGITransport(app=gateway.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, json=payload)


async def main() -> None:
    """执行 v3 的主要离线契约测试。"""
    original_get_adapter = gateway.get_adapter
    original_configs = MODEL_CONFIGS.copy()
    gateway.trace_store.clear()
    try:
        fake = FakeAdapter()
        gateway.get_adapter = lambda config: fake
        standard = await request("/v1/llm", {
            "model": "deepseek-v4-pro",
            "messages": [{"role": "user", "content": "hello"}],
            "prompt": {"name": "knowledge_decision", "version": "v1", "variables": {"product_name": "测试助手"}},
        })
        assert standard.status_code == 200, standard.text
        assert standard.json()["usage"] == {"input_tokens": 11, "output_tokens": 7}

        invalid_json = await request("/v1/llm", {
            "model": "deepseek-v4-pro", "messages": [{"role": "user", "content": "json"}],
            "response_schema": {"type": "object"},
        })
        assert invalid_json.status_code == 502 and invalid_json.json()["detail"]["code"] == "invalid_json"

        fake.content = json.dumps({"answer": "ok"})
        structured = await request("/v1/llm", {
            "model": "deepseek-v4-pro", "messages": [{"role": "user", "content": "json"}],
            "response_schema": {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]},
        })
        assert structured.status_code == 200 and structured.json()["parsed"] == {"answer": "ok"}

        schema_mismatch = await request("/v1/llm", {
            "model": "deepseek-v4-pro", "messages": [{"role": "user", "content": "json"}],
            "response_schema": {"type": "object", "properties": {"count": {"type": "integer"}}, "required": ["count"]},
        })
        assert schema_mismatch.status_code == 502 and schema_mismatch.json()["detail"]["code"] == "schema_validation_failed"

        unknown_field = await request("/v1/llm", {"model": "deepseek-v4-pro", "messages": [{"role": "user", "content": "x"}], "unknown": True})
        assert unknown_field.status_code == 422
        unknown_model = await request("/v1/llm", {"model": "not-allowed", "messages": [{"role": "user", "content": "x"}]})
        assert unknown_model.status_code == 400 and unknown_model.json()["detail"]["code"] == "unknown_model"

        fake = FakeAdapter(failures=2)
        gateway.get_adapter = lambda config: fake
        fallback = await request("/v1/llm", {"model": "deepseek-v4-pro", "messages": [{"role": "user", "content": "retry"}]})
        assert fallback.status_code == 200 and fallback.json()["model"] == "deepseek-v4-flash"
        assert fallback.json()["attempts"] == 3

        fake = FakeAdapter()
        gateway.get_adapter = lambda config: fake
        legacy = await request("/v1/chat/completions", {"model": "deepseek-v4-pro", "messages": [{"role": "user", "content": "x"}], "stream": True})
        assert legacy.status_code == 200 and '"type": "content"' in legacy.text and "[DONE]" in legacy.text
        modern = await request("/v1/llm/stream", {"model": "deepseek-v4-pro", "messages": [{"role": "user", "content": "x"}]})
        assert modern.status_code == 200 and '"type": "content.delta"' in modern.text and '"type": "response.completed"' in modern.text

        fake = FakeAdapter(stream_failure_after_first=True)
        gateway.get_adapter = lambda config: fake
        broken_stream = await request("/v1/llm/stream", {"model": "deepseek-v4-pro", "messages": [{"role": "user", "content": "x"}]})
        assert '"type": "response.failed"' in broken_stream.text and fake.calls == [MODEL_CONFIGS["deepseek-v4-pro"].provider_model]

        missing_variable = await request("/v1/llm", {"model": "deepseek-v4-pro", "messages": [{"role": "user", "content": "x"}], "prompt": {"name": "knowledge_decision", "version": "v1", "variables": {}}})
        assert missing_variable.status_code == 400 and missing_variable.json()["detail"]["code"] == "missing_prompt_variable"
        assert all("content" not in item for item in (await request_traces()).json())

        limiter = RateLimiter({"test": 2})
        assert [limiter.allow_request("test") for _ in range(3)] == [True, True, False]
        bounded_store = TraceStore(max_records=2)
        for index in range(3):
            bounded_store.record(str(index), "deepseek-v4-pro", "deepseek-v4-pro", None, Usage(input_tokens=1, output_tokens=1), 1, 1, "success")
        assert [item.request_id for item in bounded_store.list_records()] == ["1", "2"]
        print("LLM Gateway v3 离线验证通过")
    finally:
        gateway.get_adapter = original_get_adapter
        MODEL_CONFIGS.clear()
        MODEL_CONFIGS.update(original_configs)


async def request_traces() -> httpx.Response:
    """读取审计记录，用于确认审计数据不包含正文。"""
    transport = httpx.ASGITransport(app=gateway.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/v1/traces")


if __name__ == "__main__":
    asyncio.run(main())
