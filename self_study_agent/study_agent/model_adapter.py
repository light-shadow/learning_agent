"""OpenAI-compatible 模型适配器。"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict
from typing import Any, Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .errors import StudyError

T = TypeVar("T", bound=BaseModel)
LOGGER = logging.getLogger(__name__)


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
        """读取模型配置，不在构造阶段发起网络请求。"""
        self._base_url = os.getenv("STUDY_AGENT_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
        self._api_key = os.getenv("DEEPSEEK_API_KEY", "")
        self._model = os.getenv("STUDY_AGENT_MODEL", "deepseek-chat")

    @property
    def available(self) -> bool:
        """仅当网关地址、密钥和模型名齐全时允许生成学习内容。"""
        return bool(self._base_url and self._api_key and self._model)

    def generate(self, system_prompt: str, payload: dict[str, Any], result_model: type[T]) -> T:
        """请求 JSON 输出，并将不合法响应转为稳定错误。"""
        if not self.available:
            raise StudyError("MODEL_UNAVAILABLE", "未配置 STUDY_AGENT_BASE_URL、API_KEY 和 MODEL")
        schema = json.dumps(result_model.model_json_schema(), ensure_ascii=False)
        body = {
            "model": self._model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        f"{system_prompt}\n\n"
                        "必须仅输出一个 JSON 对象，不能使用 Markdown 或代码围栏。"
                        "输出必须严格符合以下 JSON Schema，不得添加未声明字段：\n"
                        f"{schema}"
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        }
        started_at = time.perf_counter()
        LOGGER.info("model_request_started model=%s result_contract=%s", self._model, result_model.__name__)
        try:
            content = self._request_content(body)
            try:
                result = _validate_model_content(content, result_model)
            except ValidationError as initial_error:
                fields = _validation_fields(initial_error)
                LOGGER.info(
                    "model_response_repair_started model=%s result_contract=%s invalid_fields=%s",
                    self._model,
                    result_model.__name__,
                    fields,
                )
                repair_body = dict(body)
                repair_body["messages"] = [
                    *body["messages"],
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": (
                            "上一份输出未通过 JSON Schema 校验。"
                            f"无效字段：{fields}。请只返回修复后的完整 JSON 对象。"
                            f"最外层 JSON 形状必须为：{_top_level_shape(result_model)}。"
                        ),
                    },
                ]
                repaired_content = self._request_content(repair_body)
                result = _validate_model_content(repaired_content, result_model)
            LOGGER.info(
                "model_request_completed model=%s result_contract=%s duration_ms=%d",
                self._model,
                result_model.__name__,
                int((time.perf_counter() - started_at) * 1000),
            )
            return result
        except StudyError:
            raise
        except ValidationError as exc:
            LOGGER.warning(
                "model_request_failed model=%s result_contract=%s duration_ms=%d invalid_fields=%s",
                self._model,
                result_model.__name__,
                int((time.perf_counter() - started_at) * 1000),
                _validation_fields(exc),
            )
            raise StudyError("MODEL_RESPONSE_INVALID", "模型两次返回的 JSON 均未通过输出契约校验") from exc
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            LOGGER.warning(
                "model_request_failed model=%s result_contract=%s duration_ms=%d error_type=%s",
                self._model,
                result_model.__name__,
                int((time.perf_counter() - started_at) * 1000),
                type(exc).__name__,
            )
            raise StudyError("MODEL_RESPONSE_INVALID", "模型服务不可用或未返回合法 JSON") from exc

    def _request_content(self, body: dict[str, Any]) -> str:
        """发送一次模型请求并只读取 JSON 响应中的内容字段。"""
        response = httpx.post(
            f"{self._base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json=body,
            timeout=30.0,
        )
        response.raise_for_status()
        return str(response.json()["choices"][0]["message"]["content"])


def _validation_fields(error: ValidationError) -> str:
    """提取有限的契约字段路径用于日志和修复请求，不输出模型原文。"""
    paths: list[str] = []
    for item in error.errors():
        path = ".".join(str(part) for part in item["loc"])
        constraints = item.get("ctx", {})
        detail = ",".join(f"{key}={value}" for key, value in constraints.items())
        suffix = f":{detail}" if detail else ""
        paths.append(f"{path}[{item['type']}{suffix}]")
    return ",".join(paths[:8]) or "unknown"


def _validate_model_content(content: str, result_model: type[T]) -> T:
    """校验模型 JSON，并兼容常见的 OpenAI-compatible 外层包装。"""
    try:
        return result_model.model_validate_json(content)
    except ValidationError as direct_error:
        normalized = _normalize_model_payload(content, result_model)
        if normalized is None:
            raise direct_error
        try:
            result = result_model.model_validate_json(json.dumps(normalized, ensure_ascii=False))
        except ValidationError:
            raise
        LOGGER.info("model_response_normalized result_contract=%s", result_model.__name__)
        return result


def _normalize_model_payload(content: str, result_model: type[T]) -> dict[str, Any] | None:
    """展开 data/result 包装或 items 列表，不改写其中的业务字段和值。"""
    try:
        stripped = _strip_markdown_fence(content)
        changed = stripped != content.strip()
        raw: Any = json.loads(stripped)
        if isinstance(raw, str):
            raw = json.loads(raw)
            changed = True
    except (TypeError, ValueError):
        return None
    fields = list(result_model.model_fields)
    if len(fields) != 1:
        return None
    root_field = fields[0]
    if isinstance(raw, list):
        return {root_field: raw}
    if not isinstance(raw, dict):
        return None
    for wrapper in ("data", "result", "output", "content"):
        wrapped = raw.get(wrapper)
        if isinstance(wrapped, list):
            return {root_field: wrapped}
        if isinstance(wrapped, dict) and root_field in wrapped:
            raw = wrapped
            changed = True
            break
    root_value = raw.get(root_field)
    if isinstance(root_value, dict):
        for wrapper in ("items", "results", "data"):
            wrapped_items = root_value.get(wrapper)
            if isinstance(wrapped_items, list):
                normalized = dict(raw)
                normalized[root_field] = wrapped_items
                return normalized
    return raw if changed else None


def _strip_markdown_fence(content: str) -> str:
    """去除模型偶发的 JSON Markdown 围栏，保留内部 JSON 原样内容。"""
    stripped = content.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        return stripped.split("\n", maxsplit=1)[-1].rsplit("```", maxsplit=1)[0].strip()
    return stripped


def _top_level_shape(result_model: type[T]) -> str:
    """从契约生成最外层 JSON 形状提示，避免写死具体响应模型。"""
    fields = list(result_model.model_fields)
    return json.dumps({field: [] for field in fields}, ensure_ascii=False)


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
