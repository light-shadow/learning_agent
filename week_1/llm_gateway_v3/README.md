# LLM Gateway v3

v3 同时支持 v2 兼容接口和新的统一 Gateway 接口，并新增结构化输出本地校验、主备切换、受控 Prompt、调用审计及稳定错误码。

## 安装与启动

```powershell
python -m pip install -r requirements.txt
$env:DEEPSEEK_API_KEY = "你的 DeepSeek API Key"
python main.py
```

可选配置包括 `DEEPSEEK_BASE_URL`、`OPENAI_API_KEY`、`ANTHROPIC_API_KEY`、模型名、价格、每分钟限流额度，以及 `LLM_GATEWAY_MAX_TRACE_RECORDS`。所有密钥仅从环境变量读取。

## 接口

- `POST /v1/chat/completions`：兼容 v2。`stream=true` 返回 `content` / `reasoning` SSE 事件和 `[DONE]`。
- `POST /v1/llm`：统一非流式接口，支持 `response_schema` 和受控 `prompt`。
- `POST /v1/llm/stream`：新 SSE 接口，返回 `content.delta`、`response.completed`、`response.failed`。
- `GET /v1/traces`：返回有界审计记录，其中包含 Token、成本、延迟、请求模型、实际模型、Prompt 版本、尝试次数和状态；不保存正文。

## 新接口示例

```json
{
  "model": "deepseek-v4-pro",
  "messages": [{"role": "user", "content": "返回北京的英文城市名"}],
  "response_schema": {
    "type": "object",
    "properties": {"city": {"type": "string"}},
    "required": ["city"],
    "additionalProperties": false
  },
  "prompt": {
    "name": "knowledge_decision",
    "version": "v1",
    "variables": {"product_name": "测试助手"}
  }
}
```

## 离线验证

无需 API Key 即可运行核心行为测试：

```powershell
python test_gateway.py
```

配置有效的 `DEEPSEEK_API_KEY` 后，可选择执行会消耗供应商额度的真实集成验证：

```powershell
python test_integration.py
```
