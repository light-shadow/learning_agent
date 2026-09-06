"""调用方 API Key 鉴权与匿名指纹计算。"""
from __future__ import annotations

import hashlib
import hmac

from fastapi import Header, Request

from app.core.errors import GatewayError


def key_fingerprint(value: str | None) -> str:
    """返回密钥或开发模式客户端标识的不可逆短指纹。"""
    return hashlib.sha256((value or "anonymous").encode("utf-8")).hexdigest()[:16]


async def authenticate(request: Request, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)) -> str:
    """校验 Bearer 或 X-API-Key；未配置网关密钥时允许开发模式访问。"""
    configured = [item.get_secret_value() for item in request.app.state.config.api_keys if item.get_secret_value()]
    if not configured:
        return key_fingerprint(request.client.host if request.client else None)
    supplied = authorization[7:].strip() if authorization and authorization.lower().startswith("bearer ") else x_api_key
    if not supplied or not any(hmac.compare_digest(supplied, candidate) for candidate in configured):
        raise GatewayError("无效或缺失 Gateway API Key", status_code=401, code="invalid_api_key", error_type="authentication_error")
    return key_fingerprint(supplied)
