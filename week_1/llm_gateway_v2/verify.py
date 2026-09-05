# verify.py
import asyncio
import aiohttp
import json
import time

from resilience.rate_limiter import RateLimiter

BASE_URL = "http://localhost:8000/v1/chat/completions"


async def ensure_success(response: aiohttp.ClientResponse) -> None:
    """校验接口响应状态，失败时输出服务端错误详情并终止验证。"""
    if response.status < 400:
        return

    error_body = await response.text()
    raise RuntimeError(
        f"请求失败，HTTP {response.status}：{error_body}"
    )


async def test_non_stream():
    """测试非流式调用"""
    payload = {
        "model": "deepseek-v4-pro",
        "messages": [{"role": "user", "content": "Hello, how are you?"}],
        "stream": False,
        "temperature": 0.7,
        "max_tokens": 100,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(BASE_URL, json=payload) as resp:
            print("Non-stream status:", resp.status)
            await ensure_success(resp)
            data = await resp.json()
            print("Non-stream response:", json.dumps(data, indent=2))
            assert "content" in data

async def test_stream():
    """测试流式调用"""
    payload = {
        "model": "deepseek-v4-flash",
        "messages": [{"role": "user", "content": "Tell me a joke."}],
        "stream": True,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(BASE_URL, json=payload) as resp:
            print("Stream status:", resp.status)
            await ensure_success(resp)
            async for line in resp.content:
                if line.startswith(b"data: "):
                    line = line[6:].strip()
                    if line == b"[DONE]":
                        break
                    try:
                        chunk = json.loads(line)
                        print("Stream chunk:", chunk)
                    except:
                        pass

async def test_template():
    """测试模板替换"""
    payload = {
        "model": "deepseek-v4-pro",
        "messages": [{"role": "user", "content": "PLACEHOLDER"}],
        "stream": False,
        "template": {
            "template_id": "summarize",
            "version": "v2",
            "variables": {"text": "The quick brown fox jumps over the lazy dog."}
        }
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(BASE_URL, json=payload) as resp:
            print("Template status:", resp.status)
            await ensure_success(resp)
            data = await resp.json()
            print("Template response:", data.get("content"))

async def test_structured_output():
    """测试结构化输出（JSON）"""
    payload = {
        "model": "deepseek-v4-pro",
        "messages": [{"role": "user", "content": "Return a JSON object with name and age."}],
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(BASE_URL, json=payload) as resp:
            print("Structured output status:", resp.status)
            await ensure_success(resp)
            data = await resp.json()
            print("Structured output:", data.get("content"))
            # 尝试解析 JSON
            try:
                json.loads(data["content"])
                print("Valid JSON")
            except:
                print("Invalid JSON")

async def test_rate_limiting():
    """使用独立的小阈值令牌桶验证限流，不消耗模型调用额度。"""
    limiter = RateLimiter({"test-model": 2})
    results = [limiter.allow_request("test-model") for _ in range(3)]
    print("Rate limit test results:", results)
    assert results == [True, True, False], "Rate limiter did not reject the excess request"

async def main():
    await test_non_stream()
    await test_stream()
    await test_template()
    await test_structured_output()
    await test_rate_limiting()
    print("All tests passed!")

if __name__ == "__main__":
    asyncio.run(main())
