# observability/metrics.py
import time
from typing import Optional
from models import ChatRequest, ChatResponse

class MetricsCollector:
    """收集单个请求的指标，并记录到日志或存储"""
    @staticmethod
    def record(request: ChatRequest, response: ChatResponse, first_token_ms: Optional[float] = None):
        # 示例：打印到 stdout，生产环境可接入 Prometheus/ELK
        print(f"""
        [Metrics] Model: {request.model}
          - Prompt tokens: {response.usage.prompt_tokens}
          - Completion tokens: {response.usage.completion_tokens}
          - Total tokens: {response.usage.total_tokens}
          - Total latency: {response.latency_ms:.2f} ms
          - First token latency: {first_token_ms if first_token_ms is not None else 'N/A'}
        """)
        # 可扩展为写入数据库或推送监控系统