**提示词：**

请生成一个基于 Python 3.12、Pydantic 2、pytest 和 OpenAI Python SDK 的可运行工程，实现最小但完整的 Agent 工具治理 Runtime。代码用于教学，必须清晰展示不可信 Tool Call 怎样经过确定性治理后才进入 handler。

## 一、核心目标

实现两种运行模式：

1. 离线治理演示：不需要 API Key，直接构造 Tool Call，验证参数校验、权限、审批、执行、脱敏和审计；
2. 可选 DeepSeek Agent Loop：通过 OpenAI-compatible API 接收真实模型 Tool Call，但所有调用仍进入同一个 `ToolRuntime.invoke()`。

完整闭环为：

```text
用户输入
→ LLM 生成 Tool Call
→ 转换为内部 ToolCall
→ ToolRuntime.prepare
→ PermissionEngine 返回 allow / deny / confirm
→ ToolRuntime.execute
→ ToolRuntime.finalize
→ 带 tool_call_id 的 ToolResult 回填 Context
→ 下一轮 LLM 或暂停确认
```

## 二、交付文件

请输出完整文件，不使用省略号：

1. `requirements.txt`
2. `pyproject.toml`
3. `tool_governance_demo.py`
4. `tests/test_tool_governance.py`

运行命令必须是：

```bash
python -m pip install -r requirements.txt
python -m py_compile tool_governance_demo.py tests/test_tool_governance.py
python tool_governance_demo.py
python -m pytest -q
```

## 三、内部对象

必须实现：

- `ToolCall`：包含 `tool_call_id`、工具名和原始参数；
- `ToolResult`：包含原始 `tool_call_id`、工具名、成功状态、`allow/deny/confirm`、稳定错误码、内容和可重试语义；
- `ToolPolicy`：包含 `effect`、`risk`、`permission`、`requires_approval`、超时、最大重试次数和幂等属性；
- `ToolDefinition`：包含名称、描述、Pydantic 参数模型、策略、handler、业务 precheck 和规范化目标函数；
- `ExecutionContext`：包含服务端生成的 trace、用户、租户、权限、本轮工具白名单、权限模式和审批 ID；
- `PermissionEngine`：只做三态决策，不执行 handler；
- `ToolRuntime`：模型、CLI、离线演示和测试共用的唯一执行入口；
- `ApprovalStore` 与 `AuditSink`。

模型只能看到工具名称、描述和 Pydantic 生成的 JSON Schema，不能看到 handler、权限集合、审批记录和内部策略。

## 四、工具与业务场景

实现三个工具：

- `get_order`：只读，权限 `order:read`，返回订单状态、可退款额、客户邮箱和模拟 access token；
- `create_refund`：高风险写操作，权限 `refund:create`，必须人工确认；
- `run_shell`：教学模拟 Shell，权限 `shell:run`，只增加计数，不启动真实子进程。

模型参数只能包含业务候选字段。`user_id`、`tenant_id`、角色、权限、`approved` 和 `approval_id` 不得出现在工具 Pydantic Model 中，只能来自服务端 `ExecutionContext`。

所有参数模型继承严格基类，使用 `extra="forbid"` 和严格类型。退款参数约束订单号格式、金额范围和原因长度。

## 五、权限三态与固定顺序

定义 `allow | deny | confirm`，每个决策包含稳定 `code`、安全 `reason` 和 `source`。必须严格按下列顺序实现，不得交换：

1. deny 规则；
2. plan 模式拒绝写操作和 Shell；
3. 执行期重新检查 `allowed_tools`；
4. RBAC 权限；
5. 租户资源归属、状态和额度等业务 precheck；
6. 高风险或 `requires_approval` 工具检查一次性参数绑定审批；
7. `bypassPermissions` 只跳过普通确认，不能跳过 1—6；
8. allow 规则；
9. 教学用危险 Shell 模式检测；
10. 默认允许。

deny 必须优先于 allow 和 bypass；plan 必须由执行层强制只读；高风险业务审批不能被 allow、bypass 或会话白名单跳过。

## 六、审批要求

审批记录必须绑定：

- `user_id`
- `tenant_id`
- `tool_name`
- 递归排序、稳定 JSON 序列化后的参数 SHA-256
- 过期时间
- 一次性 `used` 状态

批准 100 元后把金额改成 399 元，旧审批必须失效；同一个审批成功执行一次后不得重放。禁止使用 `approved=true`。

## 七、Runtime 执行要求

`ToolRuntime.invoke()` 严格分成：

1. prepare：查找工具、Pydantic 校验、权限三态决策；
2. execute：只有 allow 才调用 handler，根据只读/幂等属性选择超时与重试；
3. finalize：字段投影、递归脱敏、审计并生成 ToolResult。

任何 deny 或 confirm 都必须保证 handler 零调用。参数、权限、审批和 deny 失败不得自动重试。只读或真正幂等的工具才允许有限重试；非幂等写操作超时返回 `TIMEOUT_UNKNOWN`，禁止直接重放。

## 八、结果与审计

返回模型以前必须脱敏邮箱以及键名包含 token、secret、password、authorization 的字段。审计至少保存：

- `trace_id`
- `tool_call_id`
- 工具名
- 用户和租户
- decision / execution 阶段
- allow / deny / confirm / executed / failed
- 稳定错误码
- 参数键名
- 延迟

审计不得默认保存 Token、完整 Prompt、未经脱敏的客户资料和 Python traceback。ToolResult 必须保留原始 `tool_call_id`。

## 九、DeepSeek 可选模式

使用 `AsyncOpenAI`，从 `DEEPSEEK_API_KEY` 读取密钥；Base URL 默认 `https://api.deepseek.com`；模型从 `DEEPSEEK_MODEL` 读取，默认 `deepseek-v4-flash`；设置 `stream=True`，逐块输出文本并按 Tool Call index 累积流式名称与参数；通过 `extra_body={"thinking":{"type":"disabled"}}` 关闭思考输出。

Agent Loop 最多 8 轮。模型工具列表必须来自 Runtime 的发现期白名单；解析 Provider Tool Call 后调用同一个 `ToolRuntime.invoke()`；Tool Result 以 `role="tool"` 和原 `tool_call_id` 回填。不要在 Agent Loop 中用 if/else 分发 handler。

## 十、安全边界

- 不执行真实 Shell，不连接真实支付接口；
- 演示可以用最小危险命令正则，但注释必须说明生产环境优先使用窄工具、AST、沙箱、最小权限和 fail-closed；
- 不允许模型声明身份、租户、权限或审批；
- 不把 handler 暴露给模型；
- 不在 handler 以后才做权限判断；
- 不把原始异常堆栈交给模型；
- 不省略 `tool_call_id`；
- 不为离线测试另造一套 Fake Runtime。

## 十一、离线演示结果

至少输出：

1. 查询成功且邮箱、Token 已脱敏；
2. 未审批退款返回 `APPROVAL_REQUIRED` 和 confirm；
3. 参数绑定审批后退款成功；
4. 伪造 `user_id`、`approved` 被 Pydantic 拒绝；
5. bypass 模式下 deny 规则仍拒绝危险 Shell；
6. plan 模式拒绝退款；
7. 最终只有一次退款副作用，Shell 副作用为零，并打印审计数量。

## 十二、测试验收

至少实现八项测试：

1. deny-first：bypass 不能覆盖硬拒绝；
2. plan：写工具在审批与 allow 以前被拒绝；
3. Schema：模型不能伪造身份和确认；
4. RBAC：权限不足时 handler 零调用；
5. 审批改参：批准 100 元后改成 399 元，旧审批失效；
6. 结果边界：敏感字段脱敏，审计保留 tool_call_id；
7. 双重白名单：模型不可见，旧 Tool Call 在执行时也被拒绝；
8. 一次性审批：第一次执行成功，第二次重放返回 confirm，副作用总数为 1。

测试必须断言副作用计数，不得只断言中文错误文本。最后给出依赖说明、运行命令和预期输出摘要。
