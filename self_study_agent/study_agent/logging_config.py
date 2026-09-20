"""自学 Agent 的安全日志配置。"""

from __future__ import annotations

import logging


def configure_logging(level: str = "INFO") -> None:
    """将结构化阶段日志输出到 stderr，避免影响 CLI 的 JSON 标准输出。"""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
