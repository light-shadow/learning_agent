# LLM Gateway v4

v4 在 v3 的简化接口基础上，增加 YAML 动态路由、API Key 鉴权、身份/模型双限流、熔断、SQLite 审计、版本化 Prompt、Responses API、健康检查和 Docker 部署。

## 启动

```powershell
python -m pip install -r requirements.txt
Copy-Item .env.example .env
$env:GATEWAY_CONFIG = "gateway.example.yaml"
python main.py
```

默认使用 `gateway.example.yaml`。将其复制为 `gateway.yaml` 后按实际供应商、模型、价格和 Gateway API Key 调整；真实密钥只从环境变量读取。

运行日志默认写入 `logs/llm_gateway_v4.log`，可通过 `gateway.yaml` 的 `log_file` 修改。日志包括启动/停止、网关错误和不含请求或模型正文的调用审计字段。

## API 边界

- `POST /v1/chat/completions`：保持 v3 的简化响应与 `content` SSE 事件。
- `POST /v1/llm`、`POST /v1/llm/stream`：保持 v3 的统一协议。
- `POST /v1/responses`：新增透明 OpenAI Responses API 代理，仅支持配置为 `api: responses/both` 的 OpenAI-compatible 路由。
- `GET /v1/models`、`/v1/prompts*`、`/v1/traces`、`/admin/usage`、`/admin/routes`：模型、Prompt 与治理接口。
- `GET /healthz`、`GET /readyz`：容器健康检查。

配置 `GATEWAY_API_KEY` 后，业务与管理接口需要 `Authorization: Bearer <key>` 或 `X-API-Key`。未配置时保留开发模式访问。

## 持久化与隐私

SQLite 默认保存调用方密钥指纹、模型/供应商、Token、成本、延迟、TTFT、重试、fallback、错误和 Prompt 版本，不保存普通请求或响应正文。`stream_checkpoint.enabled` 默认为 `false`；启用后才保存流式文本，使用前应评估保留策略和访问控制。

## 验证

```powershell
python verify.py
# 安装开发依赖后：python -m pytest -q
```

`verify.py` 使用 Mock 上游，不会消耗真实模型额度。容器构建与启动：

```powershell
docker compose up --build
```

## DeepSeek 真实集成测试

`tests/test_deepseek_integration.py` 是标准 `unittest` 测试类，默认跳过，避免误消耗额度。它会经由 v4 的 `/v1/llm` 和 `/v1/llm/stream` 调用真实 DeepSeek，并校验 SQLite 审计记录。

```powershell
$env:DEEPSEEK_API_KEY = "你的 DeepSeek API Key"
$env:RUN_DEEPSEEK_INTEGRATION_TESTS = "1"
# 可选：覆盖配置中的模型别名；默认自动选择首个 DeepSeek 路由。
$env:DEEPSEEK_INTEGRATION_MODEL = "deepseek-v4-pro"
python -m unittest tests.test_deepseek_integration -v
```

如果配置了 `GATEWAY_API_KEY`，额外设置同值的 `GATEWAY_TEST_API_KEY`，使测试能够通过 Gateway 鉴权。
