# `search_orders` 最小 Function Calling 练习

这是一个完全离线的 Python 示例，使用模拟订单数据模仿餐饮开放接口的查询场景；它不会访问真实瑞幸接口，也没有鉴权、Registry、Snapshot 或重试框架。

四个练习目标分别位于：

1. `SEARCH_ORDERS_INPUT_SCHEMA` 定义工具名称、描述和 JSON Schema；
2. `SEARCH_ORDERS_TOOL` 是发给模型的 Tool JSON。它只包含协议字段，不含 handler、权限或内部依赖；
3. `run_demo()` 构造 `call_search_orders_001` 与 `call_search_orders_002` 两条 Tool Call；
4. `execute_search_orders()` 使用模拟订单生成 Tool Result，`run_demo()` 和单元测试都断言 `tool_result.tool_call_id == tool_call.id`。

在本目录执行：

```powershell
python search_orders_demo.py
python -m unittest -v test_search_orders_demo.py
```

第一条调用查询 `member-1001` 的全部订单，第二条增加 `PAID` 状态筛选。两次调用都通过 `tool_call_id` 精确关联各自的结果。
