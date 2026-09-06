"""SQLite 调用审计、成本计算与可选流式检查点。"""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from app.config import GatewayConfig

logger = logging.getLogger("llm_gateway_v4.audit")


class UsageRepository:
    """将审计事件持久化到 SQLite，不保存请求与普通响应正文。"""

    def __init__(self, database_path: str, config: GatewayConfig) -> None:
        self.database_path = database_path
        self.config = config
        self._lock = Lock()

    def initialize(self) -> None:
        """创建用量账本和可选流式检查点表。"""
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS usage_events (request_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, api_key_hash TEXT NOT NULL, endpoint TEXT NOT NULL, requested_model TEXT NOT NULL, provider TEXT, upstream_model TEXT, stream INTEGER NOT NULL, status TEXT NOT NULL, status_code INTEGER NOT NULL, input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL, cached_tokens INTEGER NOT NULL, cost_usd REAL NOT NULL, latency_ms REAL NOT NULL, first_token_ms REAL, retries INTEGER NOT NULL, fallbacks INTEGER NOT NULL, error_type TEXT, error_message TEXT, prompt_id TEXT, prompt_version INTEGER, metadata_json TEXT)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_usage_created ON usage_events(created_at)")
            db.execute("CREATE TABLE IF NOT EXISTS stream_checkpoints (request_id TEXT PRIMARY KEY, api TEXT NOT NULL, model TEXT NOT NULL, status TEXT NOT NULL, content TEXT NOT NULL, updated_at TEXT NOT NULL)")

    def record(self, event: dict[str, Any]) -> None:
        """写入一条完整调用审计记录。"""
        values = {**event, "created_at": datetime.now(timezone.utc).isoformat()}
        columns = ["request_id", "created_at", "api_key_hash", "endpoint", "requested_model", "provider", "upstream_model", "stream", "status", "status_code", "input_tokens", "output_tokens", "cached_tokens", "cost_usd", "latency_ms", "first_token_ms", "retries", "fallbacks", "error_type", "error_message", "prompt_id", "prompt_version", "metadata_json"]
        record = [values.get(column) for column in columns]
        with self._lock, self._connect() as db:
            db.execute(f"INSERT OR REPLACE INTO usage_events ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", record)
        logger.info(
            "llm_audit request_id=%s requested_model=%s provider=%s upstream_model=%s status=%s input_tokens=%s output_tokens=%s cost_usd=%s latency_ms=%s retries=%s fallbacks=%s",
            event["request_id"], event["requested_model"], event["provider"], event["upstream_model"], event["status"], event["input_tokens"], event["output_tokens"], event["cost_usd"], event["latency_ms"], event["retries"], event["fallbacks"],
        )

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        """读取最近的审计记录。"""
        with self._connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM usage_events ORDER BY created_at DESC LIMIT ?", (min(limit, 1000),)).fetchall()]

    def calculate_cost(self, model: str | None, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> float:
        """依据真实模型价格计算美元成本并区分缓存输入 Token。"""
        price = self.config.pricing.get(model or "")
        if price is None:
            return 0.0
        fresh = max(0, input_tokens - cached_tokens)
        cached_rate = price.cached_input_per_million if price.cached_input_per_million is not None else price.input_per_million
        return round((fresh * price.input_per_million + cached_tokens * cached_rate + output_tokens * price.output_per_million) / 1_000_000, 10)

    def save_checkpoint(self, request_id: str, api: str, model: str, status: str, content: str) -> None:
        """保存或更新流式正文检查点，仅在启用后由业务层调用。"""
        with self._lock, self._connect() as db:
            db.execute("INSERT INTO stream_checkpoints VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(request_id) DO UPDATE SET status=excluded.status, content=excluded.content, updated_at=excluded.updated_at", (request_id, api, model, status, content, datetime.now(timezone.utc).isoformat()))

    def get_checkpoint(self, request_id: str) -> dict[str, Any] | None:
        """读取指定请求的流式正文检查点。"""
        with self._connect() as db:
            row = db.execute("SELECT * FROM stream_checkpoints WHERE request_id = ?", (request_id,)).fetchone()
        return dict(row) if row else None

    @contextmanager
    def _connect(self):
        """创建事务连接，并确保请求结束后释放 SQLite 文件句柄。"""
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()


def usage_from_payload(payload: dict[str, Any]) -> tuple[int, int, int]:
    """归一化 Chat 和 Responses 上游响应中的 Token 用量字段。"""
    usage = payload.get("usage") or {}
    input_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
    output_tokens = int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)
    cached_tokens = int((usage.get("prompt_tokens_details", usage.get("input_tokens_details", {})) or {}).get("cached_tokens", 0) or 0)
    return input_tokens, output_tokens, cached_tokens
