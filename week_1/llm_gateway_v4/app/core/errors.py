"""统一错误和响应格式。"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("llm_gateway_v4.errors")


class GatewayError(Exception):
    """保存安全错误信息、HTTP 状态与稳定错误码。"""

    def __init__(self, message: str, *, status_code: int = 500, code: str | None = None, error_type: str = "gateway_error", details: Any = None) -> None:
        self.message = message
        self.status_code = status_code
        self.code = code
        self.error_type = error_type
        self.details = details
        super().__init__(message)


class UpstreamError(GatewayError):
    """表示上游调用失败并标识是否可以重试。"""

    def __init__(self, message: str, *, status_code: int = 502, retryable: bool = False, details: Any = None) -> None:
        self.retryable = retryable
        super().__init__(message, status_code=status_code, code="upstream_error", error_type="upstream_error", details=details)


def error_payload(error: GatewayError) -> dict[str, Any]:
    """构造 OpenAI 风格的统一错误对象。"""
    payload: dict[str, Any] = {"error": {"message": error.message, "type": error.error_type, "code": error.code}}
    if error.details is not None:
        payload["error"]["details"] = error.details
    return payload


async def gateway_error_handler(_: Request, error: GatewayError) -> JSONResponse:
    """将网关异常转换为统一 JSON 响应。"""
    logger.warning("gateway_error status=%s type=%s code=%s message=%s", error.status_code, error.error_type, error.code, error.message)
    headers = {"Retry-After": "1"} if error.status_code == 429 else None
    return JSONResponse(error_payload(error), status_code=error.status_code, headers=headers)
