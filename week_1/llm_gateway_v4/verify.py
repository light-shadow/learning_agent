"""无需真实模型与 pytest 依赖的 v4 离线验证脚本。"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from app.config import GatewayConfig
from app.main import create_app


def make_config(database: str) -> GatewayConfig:
    """构造使用 Mock 上游和固定 Gateway API Key 的最小配置。"""
    return GatewayConfig.model_validate({
        "api_keys": ["test-key"],
        "database_url": database,
        "identity_rate_limit": {"enabled": True, "requests_per_minute": 1000, "burst": 100},
        "model_rate_limit": {"enabled": True, "requests_per_minute": 1000, "burst": 100},
        "providers": {
            "primary": {"base_url": "https://primary.test", "api_key": "primary-key"},
            "fallback": {"base_url": "https://fallback.test", "api_key": "fallback-key"},
        },
        "models": {
            "smart": {"strategy": "priority", "routes": [{"provider": "primary", "model": "primary-model", "api": "both"}, {"provider": "fallback", "model": "fallback-model", "api": "both"}]},
            "chat-only": {"strategy": "priority", "routes": [{"provider": "fallback", "model": "fallback-model", "api": "chat"}]},
        },
        "pricing": {"fallback-model": {"input_per_million": 1, "output_per_million": 2}},
    })


async def main() -> None:
    """验证鉴权、fallback、结构化修复、Prompt、Responses、审计和 SSE。"""
    calls: list[tuple[str, dict]] = []
    structured_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal structured_calls
        body = json.loads(request.content)
        calls.append((request.url.host, body))
        if body.get("stream"):
            stream = (
                'data: {"choices":[{"delta":{"content":"Hi"}}]}\n\n'
                'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":1}}\n\n'
                "data: [DONE]\n\n"
            )
            return httpx.Response(200, content=stream, headers={"content-type": "text/event-stream"})
        if request.url.host == "primary.test" and body.get("model") == "primary-model":
            return httpx.Response(429, json={"error": {"message": "busy"}})
        if request.url.path == "/v1/responses":
            return httpx.Response(200, json={"id": "resp_1", "output_text": "done", "output": [], "usage": {"input_tokens": 2, "output_tokens": 1}})
        if body.get("messages", [{}])[-1].get("content", "").startswith("上一次输出"):
            structured_calls += 1
            content = '{"name":"Ada"}'
        elif any("Name" in str(item.get("content")) for item in body.get("messages", [])):
            structured_calls += 1
            content = '{"name":123}'
        else:
            content = "hello"
        return httpx.Response(200, json={"id": "chat_1", "model": body.get("model"), "choices": [{"message": {"role": "assistant", "content": content}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}})

    with TemporaryDirectory() as temp:
        upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        app = create_app(make_config(str(Path(temp) / "gateway.db")), http_client=upstream)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
                headers = {"Authorization": "Bearer test-key"}
                unauthorized = await client.get("/v1/models")
                assert unauthorized.status_code == 401
                fallback = await client.post("/v1/chat/completions", headers=headers, json={"model": "smart", "messages": [{"role": "user", "content": "hi"}]})
                assert fallback.status_code == 200 and fallback.json()["model"] == "fallback-model"
                assert [host for host, _ in calls[:3]] == ["primary.test", "primary.test", "fallback.test"]
                llm_chat_route = await client.post("/v1/llm", headers=headers, json={"model": "chat-only", "messages": [{"role": "user", "content": "llm"}]})
                assert llm_chat_route.status_code == 200, llm_chat_route.text
                structured = await client.post("/v1/llm", headers=headers, json={"model": "smart", "messages": [{"role": "user", "content": "Name"}], "response_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}})
                assert structured.status_code == 200 and structured.json()["parsed"] == {"name": "Ada"}
                created = await client.post("/v1/prompts", headers=headers, json={"id": "reviewer", "name": "Reviewer", "content": "Review {{ language }}", "role": "system"})
                assert created.status_code == 201
                rendered = await client.post("/v1/prompts/reviewer/render", headers=headers, json={"variables": {"language": "Python"}})
                assert rendered.json()["content"] == "Review Python"
                responses = await client.post("/v1/responses", headers=headers, json={"model": "smart", "input": "hello"})
                assert responses.status_code == 200 and responses.json()["output_text"] == "done"
                stream = await client.post("/v1/llm/stream", headers=headers, json={"model": "smart", "messages": [{"role": "user", "content": "stream"}]})
                assert stream.status_code == 200 and '"type": "content.delta"' in stream.text and '"type": "response.completed"' in stream.text
                usage = await client.get("/admin/usage", headers=headers)
                assert usage.status_code == 200 and usage.json()["data"] and "api_key_hash" in usage.json()["data"][0]
                assert all("content" not in item for item in usage.json()["data"])
        await upstream.aclose()
    print("LLM Gateway v4 离线验证通过")


if __name__ == "__main__":
    asyncio.run(main())
