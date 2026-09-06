"""FastAPI 应用组装与生命周期管理。"""
from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app import __version__
from app.api.routes import router
from app.config import GatewayConfig, load_config
from app.core.errors import GatewayError, error_payload, gateway_error_handler
from app.core.rate_limit import InMemoryRateLimiter
from app.services.gateway import GatewayService
from app.services.prompts import PromptRepository
from app.services.router import ModelRouter
from app.services.upstream import UpstreamClient
from app.services.usage import UsageRepository


def configure_logging(log_file: str) -> None:
    """将 v4 日志同时输出到控制台与单个 UTF-8 文件，且避免重复处理器。"""
    root_logger = logging.getLogger()
    resolved_path = str(Path(log_file).resolve())
    Path(resolved_path).parent.mkdir(parents=True, exist_ok=True)
    root_logger.setLevel(logging.INFO)
    has_file_handler = any(
        isinstance(handler, logging.FileHandler) and handler.baseFilename == resolved_path
        for handler in root_logger.handlers
    )
    if not has_file_handler:
        file_handler = logging.FileHandler(resolved_path, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        root_logger.addHandler(file_handler)
    if not root_logger.handlers:
        root_logger.addHandler(logging.StreamHandler())


def create_app(config: GatewayConfig | None = None, *, http_client: httpx.AsyncClient | None = None) -> FastAPI:
    """创建可注入配置和 HTTP Mock Client 的 v4 FastAPI 应用。"""
    gateway_config = config or load_config()
    configure_logging(gateway_config.log_file)
    logger = logging.getLogger("llm_gateway_v4")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        Path(gateway_config.database_url).parent.mkdir(parents=True, exist_ok=True)
        prompts = PromptRepository(gateway_config.database_url)
        usage = UsageRepository(gateway_config.database_url, gateway_config)
        prompts.initialize()
        usage.initialize()
        model_router = ModelRouter(gateway_config)
        upstream = UpstreamClient(gateway_config, http_client)
        app.state.config = gateway_config
        app.state.prompts = prompts
        app.state.usage = usage
        app.state.router = model_router
        app.state.gateway = GatewayService(gateway_config, model_router, upstream, prompts, usage)
        app.state.identity_limiter = InMemoryRateLimiter(gateway_config.identity_rate_limit)
        app.state.model_limiter = InMemoryRateLimiter(gateway_config.model_rate_limit)
        logger.info("gateway_started service=%s log_file=%s", gateway_config.service_name, gateway_config.log_file)
        yield
        await upstream.close()
        logger.info("gateway_stopped service=%s", gateway_config.service_name)

    app = FastAPI(title="LLM Gateway v4", version=__version__, lifespan=lifespan)
    app.add_exception_handler(GatewayError, gateway_error_handler)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse({"error": {"message": "请求参数不合法", "type": "invalid_request_error", "code": "validation_error", "details": exc.errors()}}, status_code=422)

    app.include_router(router)
    return app


app = create_app()
