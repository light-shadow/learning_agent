"""离线 Agent Runtime 的端到端测试。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import httpx

# 兼容从仓库根目录执行 unittest 与 IDE 直接执行测试文件两种方式。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.main import create_app


class AgentRuntimeTest(unittest.IsolatedAsyncioTestCase):
    """验证 Runtime 的离线 HTTP 工具调用和输入校验。"""

    async def asyncSetUp(self) -> None:
        """创建当前测试独享的应用和进程内 ASGI 客户端。"""
        self.app = create_app()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://testserver",
        )

    async def asyncTearDown(self) -> None:
        """关闭进程内 HTTP 客户端，释放测试使用的资源。"""
        await self.client.aclose()

    async def test_agent_run_creates_ticket_through_in_process_http_handler(self) -> None:
        """验证规划器通过进程内 HTTP handler 创建工单，且不需要真实网络。"""
        response = await self.client.post(
            "/v1/agent/runs",
            json={"user_id": "member-1001", "message": "订单漏送了一杯咖啡，无法正常取餐。"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["tool_calls"][0]["tool_name"], "create_ticket")
        self.assertEqual(payload["tool_calls"][0]["status"], "success")
        self.assertEqual(payload["tool_calls"][0]["output"]["ticket_id"], "TKT-000001")
        self.assertEqual(payload["tool_calls"][0]["output"]["category"], "order")
        self.assertEqual(payload["tool_calls"][0]["output"]["priority"], "high")

        ticket_response = await self.client.get("/internal/tools/tickets/TKT-000001")
        self.assertEqual(ticket_response.status_code, 200, ticket_response.text)
        self.assertEqual(ticket_response.json()["reporter_id"], "member-1001")

    async def test_agent_run_rejects_empty_message(self) -> None:
        """验证入口会拒绝空白问题，避免创建无意义工单。"""
        response = await self.client.post(
            "/v1/agent/runs",
            json={"user_id": "member-1001", "message": "   "},
        )

        self.assertEqual(response.status_code, 422)
