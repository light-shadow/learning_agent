"""本地启动离线 Agent Runtime 的脚本。"""
from __future__ import annotations

import uvicorn


def main() -> None:
    """仅在本机回环地址启动用于手动验证的 ASGI 服务。"""
    uvicorn.run("app.main:app", host="127.0.0.1", port=8002, reload=False)


if __name__ == "__main__":
    main()
