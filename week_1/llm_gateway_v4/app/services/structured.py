"""结构化输出提取、JSON Schema 校验与修复提示生成。"""
from __future__ import annotations

import json
import re
from typing import Any

from jsonschema import ValidationError, validate

from app.core.errors import GatewayError

_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)


def extract_schema(api: str, body: dict[str, Any]) -> dict[str, Any] | None:
    """从三种支持的请求协议中提取 JSON Schema。"""
    if api == "responses":
        return ((body.get("text") or {}).get("format") or {}).get("schema") if ((body.get("text") or {}).get("format") or {}).get("type") == "json_schema" else None
    if "response_schema" in body:
        return body.get("response_schema")
    response_format = body.get("response_format") or {}
    if response_format.get("type") == "json_schema":
        return response_format.get("schema") or (response_format.get("json_schema") or {}).get("schema")
    return {"type": "object"} if response_format.get("type") == "json_object" else None


def content_from_response(api: str, payload: dict[str, Any]) -> str:
    """从 Chat 或 Responses 响应中提取模型文本。"""
    try:
        if api in ("chat", "llm"):
            return str(payload["choices"][0]["message"].get("content") or "")
        if isinstance(payload.get("output_text"), str):
            return payload["output_text"]
        for output in payload.get("output", []):
            for item in output.get("content", []):
                if item.get("type") in ("output_text", "text"):
                    return str(item.get("text") or "")
    except (KeyError, IndexError, TypeError):
        pass
    raise GatewayError("无法提取模型文本", status_code=422, code="invalid_model_output", error_type="structured_output_error")


def validate_response(api: str, payload: dict[str, Any], schema: dict[str, Any] | None) -> dict[str, Any] | list[Any] | None:
    """校验结构化响应，并允许单个 Markdown JSON 围栏。"""
    if schema is None:
        return None
    content = content_from_response(api, payload)
    fenced = _FENCE.match(content)
    if fenced:
        content = fenced.group(1)
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise GatewayError("模型输出不是合法 JSON", status_code=422, code="invalid_model_output", error_type="structured_output_error", details={"line": exc.lineno, "column": exc.colno}) from exc
    try:
        validate(instance=parsed, schema=schema)
    except ValidationError as exc:
        raise GatewayError("模型输出不符合 JSON Schema", status_code=422, code="invalid_model_output", error_type="structured_output_error", details={"path": list(exc.absolute_path), "message": exc.message}) from exc
    if not isinstance(parsed, (dict, list)):
        raise GatewayError("结构化输出必须为对象或数组", status_code=422, code="invalid_model_output", error_type="structured_output_error")
    return parsed


def repair_instruction(error: GatewayError, schema: dict[str, Any]) -> str:
    """构造包含具体校验原因的模型修复指令。"""
    return "上一次输出未通过 JSON Schema 校验。只返回修正后的 JSON，不要 Markdown 或解释。\n" + json.dumps({"error": error.message, "details": error.details, "schema": schema}, ensure_ascii=False)
