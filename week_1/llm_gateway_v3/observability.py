"""调用审计和结构化日志能力。"""
from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timezone

from config import MAX_TRACE_RECORDS, MODEL_CONFIGS
from models import CallTrace, PromptSelection, Usage

logger = logging.getLogger("llm_gateway_v3")


class TraceStore:
    """保存固定数量调用审计记录的进程内存储。"""

    def __init__(self, max_records: int = MAX_TRACE_RECORDS) -> None:
        self._records: deque[CallTrace] = deque(maxlen=max_records)

    def record(
        self,
        request_id: str,
        requested_model: str,
        actual_model: str | None,
        prompt: PromptSelection | None,
        usage: Usage,
        latency_ms: int,
        attempts: int,
        status: str,
        error_code: str | None = None,
    ) -> None:
        """记录一次调用的 Token、成本、延迟、模型、模板和尝试次数。"""
        config = MODEL_CONFIGS.get(actual_model) if actual_model else None
        cost_usd = 0.0
        if config is not None:
            cost_usd = (
                usage.input_tokens * config.input_price_per_million
                + usage.output_tokens * config.output_price_per_million
            ) / 1_000_000
        trace = CallTrace(
            request_id=request_id,
            timestamp=datetime.now(timezone.utc),
            requested_model=requested_model,
            actual_model=actual_model,
            prompt_name=prompt.name if prompt else None,
            prompt_version=prompt.version if prompt else None,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            attempts=attempts,
            status=status,
            error_code=error_code,
        )
        self._records.append(trace)
        logger.info("llm_call_trace=%s", trace.model_dump_json())

    def list_records(self) -> list[CallTrace]:
        """返回审计记录快照，避免调用方修改内部队列。"""
        return list(self._records)

    def clear(self) -> None:
        """清空审计记录，供离线测试隔离状态使用。"""
        self._records.clear()


trace_store = TraceStore()
