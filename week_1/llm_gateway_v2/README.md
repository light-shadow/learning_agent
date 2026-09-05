# LLM Gateway v2

一个基于 FastAPI 的轻量级大模型网关示例。它对外提供统一的聊天补全接口，依据请求中的逻辑模型名选择适配器，将请求转发给 DeepSeek，并将非流式响应归一为统一结构。

> 本项目定位为学习/演示代码。默认模型路由已直连 DeepSeek 官方 API；模型名与 API 地址均可在 `config.py` 或环境变量中调整。

## 功能概览

- 统一接口：`POST /v1/chat/completions`。
- 多协议适配：默认通过 `DeepSeekAdapter` 调用 DeepSeek 的 OpenAI 兼容接口；项目仍保留 OpenAI 和 Anthropic 适配器，便于扩展路由。
- 流式输出：`stream=true` 时以 Server-Sent Events（SSE）逐块返回内容，结束标记为 `[DONE]`。
- 结构化输出：当前稳定示例为 `response_format.type=json_object`；OpenAI 会传递 JSON Object 约束，Anthropic 通过提示词约束输出 JSON。
- 提示词模板：内置内存模板，支持版本与 `{{变量名}}` 替换。
- 韧性能力：每个模型独立令牌桶限流、最多 3 次指数退避重试。
- 可观测性：非流式请求会将 Token 用量和总延迟输出到标准输出。

## 模型路由

默认映射位于 [config.py](config.py)：

| 对外 `model` | 适配器 | 默认实际模型 | 每分钟上限 |
| --- | --- | --- | --- |
| `deepseek-v4-pro` | DeepSeek | `deepseek-v4-pro` | 100 |
| `deepseek-v4-flash` | DeepSeek | `deepseek-v4-flash` | 120 |

可按账号可用模型修改 `MODEL_ROUTING`。请求中使用未配置的逻辑模型名会被 Pydantic 校验拦截，并返回 HTTP 422。

## 目录结构

```text
llm_gateway_v2/
├── main.py                    # Uvicorn 启动入口
├── gateway.py                 # 路由、网关编排和统一异常处理
├── config.py                  # 路由、密钥、限流和重试配置
├── models.py                  # 请求/响应数据模型
├── adapters/
│   ├── base.py                # 适配器抽象接口
│   ├── deepseek_adapter.py    # DeepSeek OpenAI 兼容接口适配器
│   ├── openai_adapter.py      # OpenAI Chat Completions 适配器
│   └── anthropic_adapter.py   # Anthropic Messages 适配器
├── templates/manager.py       # 内存模板与变量渲染
├── observability/metrics.py   # 控制台指标输出
├── resilience/
│   ├── retry.py               # 异步指数退避重试
│   └── rate_limiter.py        # 按模型限流
├── verify.py                  # 手工验证脚本
└── requirements.txt
```

## 环境要求

- Python 3.9+
- 可访问 DeepSeek API 的网络环境
- 有效的 DeepSeek API Key，以及对 `config.py` 中实际模型的调用权限

## 安装与启动

在本目录执行以下命令。PowerShell 示例：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

$env:DEEPSEEK_API_KEY = "你的 DeepSeek API Key"
python main.py
```

服务默认监听 `http://0.0.0.0:8000`。启动后可访问：

- Swagger UI：`http://127.0.0.1:8000/docs`
- OpenAPI 文档：`http://127.0.0.1:8000/openapi.json`

也可以使用 Uvicorn 启动：

```powershell
uvicorn gateway:app --host 0.0.0.0 --port 8000 --reload
```

不要依赖 `config.py` 中 `DEEPSEEK_API_KEY` 的空默认值；必须通过系统环境变量或自行扩展配置加载逻辑注入有效密钥。虽然依赖列表含有 `python-dotenv`，当前代码尚未加载 `.env` 文件。

## 聊天补全接口

### 非流式请求

```bash
curl -X POST "http://127.0.0.1:8000/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-v4-pro",
    "messages": [
      {"role": "system", "content": "你是一名简洁的助手。"},
      {"role": "user", "content": "用一句话介绍大模型网关。"}
    ],
    "temperature": 0.7,
    "max_tokens": 100
  }'
```

成功响应示例：

```json
{
  "id": "chatcmpl-xxx",
  "model": "deepseek-v4-pro",
  "content": "大模型网关通过统一接口管理不同厂商模型的调用。",
  "usage": {
    "prompt_tokens": 20,
    "completion_tokens": 18,
    "total_tokens": 38
  },
  "reasoning": null,
  "latency_ms": 356.8,
  "first_token_latency_ms": null
}
```

### 流式请求

使用 `-N` 关闭 curl 缓冲：

```bash
curl -N -X POST "http://127.0.0.1:8000/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-v4-flash",
    "messages": [{"role": "user", "content": "讲一个短笑话。"}],
    "stream": true
  }'
```

返回数据是 SSE，每一块的格式类似：

```text
data: {"type": "content", "content": "..."}

data: [DONE]
```

### JSON Object 输出

```bash
curl -X POST "http://127.0.0.1:8000/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-v4-pro",
    "messages": [{"role": "user", "content": "返回包含 name 和 age 的 JSON 对象。"}],
    "response_format": {"type": "json_object"}
  }'
```

响应正文的 `content` 字段是模型返回的 JSON 文本，调用方仍应自行执行 JSON 解析和业务字段校验。

## 提示词模板

当前内置模板保存在 [templates/manager.py](templates/manager.py)：

| 模板 ID | 版本 | 作用 | 变量 |
| --- | --- | --- | --- |
| `summarize` | `v1`、`v2` | 文本概括 | `text` |
| `translate` | `v1` | 翻译 | `text`、`target_lang` |

模板会替换最后一条 `user` 消息的内容；若消息列表最后一条不是 `user`，则会追加一条 `user` 消息。

```bash
curl -X POST "http://127.0.0.1:8000/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-v4-pro",
    "messages": [{"role": "user", "content": "占位内容"}],
    "template": {
      "template_id": "summarize",
      "version": "v2",
      "variables": {"text": "这里是需要概括的长文本。"}
    }
  }'
```

查询已有模板：

```bash
curl "http://127.0.0.1:8000/v1/templates/summarize?version=v2"
```

## 配置说明

`config.py` 包含以下可调整项：

| 配置项 | 含义 |
| --- | --- |
| `MODEL_ROUTING` | 逻辑模型名到适配器类型和实际模型名的映射 |
| `DEEPSEEK_API_KEY` | 从环境变量读取的 DeepSeek API Key |
| `DEEPSEEK_BASE_URL` | DeepSeek API 地址，默认 `https://api.deepseek.com` |
| `RATE_LIMITS` | 每个逻辑模型每分钟可通过的请求数 |
| `RETRY_CONFIG` | 重试配置常量；当前网关装饰器中使用同样的固定值 |

限流器为进程内实现，多进程或多实例部署时不会共享配额。生产环境建议替换为 Redis 等集中式限流方案，并结合用户、租户或 API Key 维度进行控制。

## 验证脚本

`verify.py` 包含非流式、流式、模板、JSON Object 和限流场景的示例。前四项会调用上游模型；限流项使用独立的小阈值令牌桶进行本地验证，不会额外消耗模型调用额度。它额外依赖 `aiohttp`，运行前安装：

```powershell
python -m pip install aiohttp
python verify.py
```

限流验证预期输出为 `Rate limit test results: [True, True, False]`，其中第三次请求被令牌桶拒绝。默认网关的限流配置仍由 `RATE_LIMITS` 控制。

## 当前实现边界与后续建议

- `POST /v1/templates` 目前是占位接口，尚未实现创建和持久化；模板仅保存在进程内存中，重启后不会保留。
- 流式路径会返回文本块和 `[DONE]`，但当前未记录流式 Token 用量、总延迟或首 Token 延迟。
- `response_format` 的 `json_schema` 虽被请求模型接受，但适配层尚未完成两家厂商的统一转换与严格校验；建议当前只使用 `json_object`。
- 重试会处理 429 和部分 5xx。生产环境应增加抖动、超时、熔断与对不可重试错误的精细分类。
- 生产部署应移除占位密钥、限制 CORS/鉴权范围、使用密钥管理服务，并将日志和指标接入集中式观测平台。

## 常见问题

**返回 422 Unsupported model**：检查请求的 `model` 是否与 `MODEL_ROUTING` 的键完全一致。

**返回 429**：已触发该逻辑模型的进程内限流；等待令牌补充，或按容量规划调整 `RATE_LIMITS`。

**上游调用失败**：确认 `DEEPSEEK_API_KEY` 已在启动服务的同一终端中设置，并确认实际模型名、账号权限和网络访问均有效。
