"""可选的真实 DeepSeek 集成验证脚本，默认不会自动执行。"""
from __future__ import annotations

import asyncio
import os

import httpx

import gateway


async def main() -> None:
    """使用环境变量中的真实密钥验证非流式、结构化和流式接口。"""
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise RuntimeError("未检测到 DEEPSEEK_API_KEY，无法执行真实集成测试")

    transport = httpx.ASGITransport(app=gateway.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway-test", timeout=90) as client:
        normal = await client.post("/v1/llm", json={
            "model": "deepseek-v4-pro",
            "messages": [{"role": "user", "content": "只回复 PONG。"}],
        })
        assert normal.status_code == 200, normal.text

        structured = await client.post("/v1/llm", json={
            "model": "deepseek-v4-pro",
            "messages": [{"role": "user", "content": "只返回 JSON：{\"value\": \"ok\"}"}],
            "response_schema": {
                "type": "object",
                "properties": {"value": {"type": "string", "const": "ok"}},
                "required": ["value"],
                "additionalProperties": False,
            },
        })
        assert structured.status_code == 200, structured.text
        assert structured.json()["parsed"] == {"value": "ok"}

        stream = await client.post("/v1/llm/stream", json={
            "model": "deepseek-v4-pro",
            "messages": [{"role": "user", "content": "只回复 STREAM_OK。"}],
        })
        assert stream.status_code == 200, stream.text
        assert '"type": "response.completed"' in stream.text, stream.text
    print("真实 DeepSeek 集成验证通过")


if __name__ == "__main__":
    asyncio.run(main())
