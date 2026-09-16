# 离线 Agent Runtime 骨架

这是第二周的最小 Agent Runtime：它使用确定性规则规划任务，再调用 `create_ticket` 工具。没有模型 API、模型密钥、外部服务地址，也不会访问瑞幸、麦当劳或其他真实网络。

`create_ticket` 的契约借鉴了餐饮业务工具常见的「工具名 + 结构化入参 + 结构化结果」形式，但实现是本项目的假内部接口：

- 对外运行入口：`POST /v1/agent/runs`
- 假内部工具 handler：`POST /internal/tools/create_ticket`
- 工具调用方式：`httpx.ASGITransport` 在同一 Python 进程内分发请求，不会打开 socket 或发起真实 HTTP 网络请求。
- 数据存储：进程内内存；重启应用后工单会清空。

## 环境与依赖

通过 `conda env list` 核对后，本机实际环境路径为 `H:\conda_envs\ai-agent`（与请求中的 `H:\conda\_envs\ai-agent` 不同）。该环境当前具备：Python 3.13.12、FastAPI 0.115.6、HTTPX 0.27.2、Pydantic 2.10.4。

`requirements.txt` 固定记录的是该环境已经安装并被本示例使用的版本；运行本骨架不需要额外安装包。

## 运行测试

```powershell
conda run -p H:\conda_envs\ai-agent python -m unittest discover -s week_2\agent_runtime\tests -v
```

测试通过 FastAPI 的 ASGI 进程内传输执行全链路，不依赖本机端口，也不访问网络。

## 可选：本地手动启动

```powershell
Set-Location week_2\agent_runtime
conda run -p H:\conda_envs\ai-agent python main.py
```

该命令仅监听 `127.0.0.1:8002`，供本机手动调试。示例请求：

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8002/v1/agent/runs -ContentType 'application/json' -Body '{"user_id":"member-1001","message":"订单漏送了一杯咖啡，无法正常取餐。"}'
```

## 执行链路

```text
POST /v1/agent/runs
        |
RuleBasedPlanner（无需 LLM）
        |
ToolRegistry -> create_ticket
        |
httpx.ASGITransport（进程内、无真实网络）
        |
POST /internal/tools/create_ticket -> InMemoryTicketStore
```

后续接入真实模型或真实内部服务时，可保留 `AgentRuntime`、`ToolRegistry` 和 Pydantic 契约，分别替换 `RuleBasedPlanner` 与 `InProcessCreateTicketClient`。
