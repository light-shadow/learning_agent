"""pytest 入口复用离线验证逻辑，供 CI 使用。"""
import pytest

from verify import main


@pytest.mark.asyncio
async def test_gateway_end_to_end() -> None:
    """验证 v4 核心离线契约。"""
    await main()
