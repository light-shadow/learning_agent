"""模拟内部工单服务的 HTTP handler，仅在当前 ASGI 进程内使用。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.schemas import CreateTicketInput, Ticket
from app.ticket_store import InMemoryTicketStore

router = APIRouter(prefix="/internal/tools", tags=["internal-tools"])


def _get_ticket_store(request: Request) -> InMemoryTicketStore:
    """从应用状态中取得本次运行使用的内存工单存储。"""
    return request.app.state.ticket_store


@router.post("/create_ticket", response_model=Ticket, status_code=status.HTTP_201_CREATED)
async def create_ticket(ticket_input: CreateTicketInput, request: Request) -> Ticket:
    """模拟内部 create_ticket HTTP 接口，创建并返回一张假工单。"""
    return await _get_ticket_store(request).create(ticket_input)


@router.get("/tickets/{ticket_id}", response_model=Ticket)
async def get_ticket(ticket_id: str, request: Request) -> Ticket:
    """查询假内部工单，辅助本地联调和测试断言。"""
    ticket = await _get_ticket_store(request).get(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="工单不存在")
    return ticket
