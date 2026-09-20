"""OpenAI-compatible 模型适配器与离线回退策略。"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Any, Protocol, TypeVar

import httpx
from pydantic import BaseModel

from .errors import StudyError

T = TypeVar("T", bound=BaseModel)


class JsonModel(Protocol):
    """定义知识提炼和评分所需的最小模型协议。"""

    @property
    def available(self) -> bool:
        """指示模型配置是否完整。"""

    def generate(self, system_prompt: str, payload: dict[str, Any], result_model: type[T]) -> T:
        """生成并校验指定 Pydantic 结果。"""


class OpenAICompatibleModel:
    """通过环境变量调用 OpenAI-compatible Chat Completions 服务。"""

    def __init__(self) -> None:
        """读取可选模型配置，不在构造阶段发起网络请求。"""
        self._base_url = os.getenv("STUDY_AGENT_BASE_URL", "").rstrip("/")
        self._api_key = os.getenv("STUDY_AGENT_API_KEY", "")
        self._model = os.getenv("STUDY_AGENT_MODEL", "")

    @property
    def available(self) -> bool:
        """仅当网关地址、密钥和模型名齐全时启用模型模式。"""
        return bool(self._base_url and self._api_key and self._model)

    def generate(self, system_prompt: str, payload: dict[str, Any], result_model: type[T]) -> T:
        """请求 JSON 输出，并将不合法响应转为稳定错误。"""
        if not self.available:
            raise StudyError("MODEL_UNAVAILABLE", "未配置 STUDY_AGENT_BASE_URL、API_KEY 和 MODEL")
        body = {
            "model": self._model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        }
        try:
            response = httpx.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=body,
                timeout=30.0,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return result_model.model_validate_json(content)
        except StudyError:
            raise
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise StudyError("MODEL_RESPONSE_INVALID", "模型服务不可用或未返回合法 JSON") from exc


class FakeJsonModel:
    """测试使用的固定 JSON 模型，不产生网络请求。"""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        """保存依次返回的结构化测试响应。"""
        self._responses = list(responses)

    @property
    def available(self) -> bool:
        """测试模型始终视为可用。"""
        return True

    def generate(self, system_prompt: str, payload: dict[str, Any], result_model: type[T]) -> T:
        """忽略提示词并按约定顺序返回预设结果。"""
        if not self._responses:
            raise StudyError("MODEL_RESPONSE_INVALID", "测试模型没有剩余响应")
        return result_model.model_validate(self._responses.pop(0))
