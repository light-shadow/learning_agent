"""DeepSeek 真实集成测试：默认跳过，显式开启后才会访问上游并消耗额度。"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

import httpx

# 兼容 IDE 直接执行 tests 下的文件和 unittest 模块化运行两种方式。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import GatewayConfig, load_config
from app.main import create_app


def _enabled() -> bool:
    """仅在显式开启且配置了 DeepSeek 密钥时执行真实集成测试。"""
    return os.getenv("RUN_DEEPSEEK_INTEGRATION_TESTS") == "1" and bool(os.getenv("DEEPSEEK_API_KEY"))


@unittest.skipUnless(
    _enabled(),
    "真实 DeepSeek 测试默认跳过；请设置 DEEPSEEK_API_KEY 和 RUN_DEEPSEEK_INTEGRATION_TESTS=1",
)
class DeepSeekGatewayIntegrationTest(unittest.IsolatedAsyncioTestCase):
    """通过 v4 HTTP 接口验证 DeepSeek 非流式、流式和审计链路。"""

    async def asyncSetUp(self) -> None:
        """加载 Gateway 配置、创建应用生命周期并准备 ASGI 测试客户端。"""
        self.config: GatewayConfig = load_config(os.getenv("GATEWAY_CONFIG"))
        self.model = os.getenv("DEEPSEEK_INTEGRATION_MODEL", self._find_deepseek_model())
        if self.model not in self.config.models:
            self.skipTest(f"配置中不存在 DeepSeek 测试模型别名: {self.model}")
        self.app = create_app(self.config)
        self.lifespan = self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://deepseek-integration-test",
            timeout=120,
        )

    async def asyncTearDown(self) -> None:
        """关闭 ASGI 客户端和应用生命周期，释放 HTTP 与 SQLite 资源。"""
        await self.client.aclose()
        await self.lifespan.__aexit__(None, None, None)

    def _find_deepseek_model(self) -> str:
        """从配置中找到首个包含 DeepSeek 供应商路由的逻辑模型别名。"""
        for alias, route_config in self.config.models.items():
            if any("deepseek" in route.provider.lower() for route in route_config.routes):
                return alias
        self.skipTest("gateway.yaml 中未配置 DeepSeek 路由")
        return ""

    def _headers(self) -> dict[str, str]:
        """在启用 Gateway API Key 时提供测试身份认证请求头。"""
        api_key = os.getenv("GATEWAY_TEST_API_KEY") or os.getenv("GATEWAY_API_KEY")
        return {"Authorization": f"Bearer {api_key}"} if api_key else {}

    async def test_non_stream_llm_and_audit(self) -> None:
        """验证 DeepSeek 可返回 LLM 响应、Token 用量和对应持久化审计记录。"""
        response = await self.client.post(
            "/v1/llm",
            headers=self._headers(),
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": "只回复 DEEPSEEK_GATEWAY_OK，不要解释。"}],
                "timeout_seconds": 90,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload["request_id"])
        self.assertTrue(payload["content"].strip())
        self.assertGreaterEqual(payload["usage"]["input_tokens"], 0)
        self.assertGreaterEqual(payload["usage"]["output_tokens"], 0)
        self.assertGreaterEqual(payload["latency_ms"], 0)

        audit = await self.client.get("/admin/usage?limit=20", headers=self._headers())
        self.assertEqual(audit.status_code, 200, audit.text)
        record = next((item for item in audit.json()["data"] if item["request_id"] == payload["request_id"]), None)
        self.assertIsNotNone(record, "未找到本次真实调用的 SQLite 审计记录")
        self.assertEqual(record["status"], "success")
        self.assertTrue(record["upstream_model"])
        self.assertNotIn("content", record)

    async def test_stream_llm(self) -> None:
        """验证 DeepSeek 流式响应包含内容增量和完成事件。"""
        response = await self.client.post(
            "/v1/llm/stream",
            headers=self._headers(),
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": "只回复 STREAM_OK，不要解释。"}],
                "timeout_seconds": 90,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
        self.assertIn('"type": "content.delta"', response.text)
        self.assertIn('"type": "response.completed"', response.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
