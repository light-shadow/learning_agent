"""用于演示的内存工单存储。"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.schemas import CreateTicketInput, Ticket


class InMemoryTicketStore:
    """以进程内存保存假工单，便于离线验证完整链路。"""

    def __init__(self) -> None:
        """初始化工单序号、数据容器与并发保护锁。"""
        self._lock = asyncio.Lock()
        self._next_number = 1
        self._tickets: dict[str, Ticket] = {}

    async def create(self, ticket_input: CreateTicketInput) -> Ticket:
        """创建一条状态为 open 的假工单并返回其完整记录。"""
        async with self._lock:
            ticket_id = f"TKT-{self._next_number:06d}"
            self._next_number += 1
            ticket = Ticket(
                ticket_id=ticket_id,
                reporter_id=ticket_input.reporter_id,
                title=ticket_input.title,
                description=ticket_input.description,
                category=ticket_input.category,
                priority=ticket_input.priority,
                status="open",
                created_at=datetime.now(timezone.utc),
            )
            self._tickets[ticket_id] = ticket
            return ticket

    async def get(self, ticket_id: str) -> Ticket | None:
        """按工单号读取已创建的假工单。"""
        async with self._lock:
            return self._tickets.get(ticket_id)
