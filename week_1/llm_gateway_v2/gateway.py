# gateway.py
import uuid
import asyncio
import time
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
import json
from typing import Dict, Any, AsyncGenerator

from models import ChatRequest, ChatResponse, Message
from adapters.deepseek_adapter import DeepSeekAdapter
from adapters.openai_adapter import OpenAIAdapter
from adapters.anthropic_adapter import AnthropicAdapter
from adapters.base import BaseAdapter
from config import MODEL_ROUTING, DEEPSEEK_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY
from templates.manager import TemplateManager
from observability.metrics import MetricsCollector
from resilience.retry import async_retry
from resilience.rate_limiter import rate_limiter

app = FastAPI(title="LLM Gateway")

def get_adapter(model: str, api_key: str = None) -> BaseAdapter:
    """工厂方法获取适配器"""
    adapter_type, real_model = MODEL_ROUTING[model]
    if adapter_type == "deepseek":
        return DeepSeekAdapter(real_model, api_key or DEEPSEEK_API_KEY)
    elif adapter_type == "openai":
        return OpenAIAdapter(real_model, api_key or OPENAI_API_KEY)
    elif adapter_type == "anthropic":
        return AnthropicAdapter(real_model, api_key or ANTHROPIC_API_KEY)
    else:
        raise ValueError(f"Unknown adapter type {adapter_type}")

@async_retry(max_attempts=3, base_delay=1.0, max_delay=10.0, exponential_base=2)
async def _call_adapter(request: ChatRequest):
    """内部调用适配器（含重试）"""
    # 限流检查
    if not rate_limiter.allow_request(request.model):
        raise HTTPException(status_code=429, detail="Rate limit exceeded for this model")

    # 应用模板（若存在）
    if request.template:
        request.messages = TemplateManager.apply_template(request)

    adapter = get_adapter(request.model)

    if request.stream:
        # 流式处理
        async def event_generator() -> AsyncGenerator[str, None]:
            start_time = time.time()
            first_token_time = None
            try:
                async for chunk in adapter.chat_completion_stream(request):
                    # 记录首 token
                    if first_token_time is None:
                        first_token_time = (time.time() - start_time) * 1000
                    # 构造 SSE 格式
                    yield f"data: {json.dumps(chunk)}\n\n"
            except Exception as e:
                # 错误信息也通过 SSE 发送
                yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
            finally:
                # 结束标记
                yield "data: [DONE]\n\n"
                # 这里无法获取 usage，可以后期改进

        return StreamingResponse(event_generator(), media_type="text/event-stream")
    else:
        # 非流式
        start_time = time.time()
        response = await adapter.chat_completion(request)
        total_latency = (time.time() - start_time) * 1000
        response.latency_ms = total_latency

        # 记录 metrics
        MetricsCollector.record(request, response, first_token_ms=None)

        # 返回统一格式
        return response

@app.post("/v1/chat/completions")
async def chat_completion(request: ChatRequest):
    """
    统一聊天补全接口
    """
    try:
        result = await _call_adapter(request)
        return result
    except HTTPException as e:
        raise e
    except Exception as e:
        # 统一错误码封装
        status_code = getattr(e, 'status_code', 500)
        error_msg = str(e)
        raise HTTPException(status_code=status_code, detail=error_msg)

# 模板管理接口（可选，用于演示）
@app.post("/v1/templates")
async def create_template():
    pass  # 可扩展

@app.get("/v1/templates/{template_id}")
async def get_template(template_id: str, version: str = None):
    tpl = TemplateManager.get_template(template_id, version)
    if not tpl:
        raise HTTPException(404, "Template not found")
    return tpl
