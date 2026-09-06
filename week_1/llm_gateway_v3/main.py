"""LLM Gateway v3 的 Uvicorn 启动入口。"""
import uvicorn

from gateway import app


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
