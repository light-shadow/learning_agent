"""OpenAI-compatible 结构化输出适配测试。"""

from __future__ import annotations

import json
from typing import Any

from study_agent import model_adapter
from study_agent.model_adapter import OpenAICompatibleModel
from study_agent.services import ConceptResponse


def test_model_adapter_repairs_invalid_structured_response(monkeypatch) -> None:
    """验证模型首次违反契约时会收到 Schema 修复请求，而不是直接放弃生成。"""
    monkeypatch.setenv("STUDY_AGENT_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("STUDY_AGENT_API_KEY", "test-key")
    monkeypatch.setenv("STUDY_AGENT_MODEL", "test-model")
    responses = iter(
        [
            {
                "concepts": [
                    {
                        "title": "Tool Runtime 的执行边界",
                        "summary": "Tool Runtime 在执行前校验参数与权限。",
                        "keywords": ["Tool Runtime"],
                        "chunk_index": 0,
                        "unexpected": True,
                    }
                ]
            },
            {
                "concepts": [
                    {
                        "title": "Tool Runtime 的执行边界",
                        "summary": "Tool Runtime 在执行前校验参数与权限。",
                        "keywords": ["Tool Runtime"],
                        "chunk_index": 0,
                    }
                ]
            },
        ]
    )
    requests: list[dict[str, Any]] = []

    class _Response:
        """模拟 OpenAI-compatible Chat Completions 响应。"""

        def __init__(self, content: dict[str, Any]) -> None:
            """保存一次响应内容。"""
            self._content = content

        def raise_for_status(self) -> None:
            """模拟 HTTP 200。"""

        def json(self) -> dict[str, Any]:
            """返回 Chat Completions 的最小响应结构。"""
            return {"choices": [{"message": {"content": json.dumps(self._content, ensure_ascii=False)}}]}

    def _post(*_args: Any, **kwargs: Any) -> _Response:
        """记录请求体并返回下一份模拟响应。"""
        requests.append(kwargs["json"])
        return _Response(next(responses))

    monkeypatch.setattr(model_adapter.httpx, "post", _post)

    result = OpenAICompatibleModel().generate("仅输出知识点。", {"chunks": []}, ConceptResponse)

    assert result.concepts[0].title == "Tool Runtime 的执行边界"
    assert len(requests) == 2
    assert "JSON Schema" in requests[0]["messages"][0]["content"]
    assert "unexpected" in requests[1]["messages"][-1]["content"]


def test_model_adapter_normalizes_common_response_wrapper(monkeypatch) -> None:
    """验证 data 包装的概念列表会在契约校验前被展开，无需额外模型请求。"""
    monkeypatch.setenv("STUDY_AGENT_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("STUDY_AGENT_API_KEY", "test-key")
    monkeypatch.setenv("STUDY_AGENT_MODEL", "test-model")
    requests: list[dict[str, Any]] = []

    class _Response:
        """模拟返回 data 包装的模型响应。"""

        def raise_for_status(self) -> None:
            """模拟 HTTP 200。"""

        def json(self) -> dict[str, Any]:
            """返回仅差外层包装的有效概念数据。"""
            content = {
                "data": [
                    {
                        "title": "Tool Runtime 的执行边界",
                        "summary": "Tool Runtime 在执行前校验参数与权限。",
                        "keywords": ["Tool Runtime"],
                        "chunk_index": 0,
                    }
                ]
            }
            return {"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]}

    def _post(*_args: Any, **kwargs: Any) -> _Response:
        """记录请求并返回固定 data 包装响应。"""
        requests.append(kwargs["json"])
        return _Response()

    monkeypatch.setattr(model_adapter.httpx, "post", _post)

    result = OpenAICompatibleModel().generate("仅输出知识点。", {"chunks": []}, ConceptResponse)

    assert result.concepts[0].chunk_index == 0
    assert len(requests) == 1
