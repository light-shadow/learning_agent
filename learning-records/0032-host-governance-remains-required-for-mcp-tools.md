# 已掌握 MCP 外部工具仍须由 Host Runtime 治理

用户能判断远程 MCP Server 的职责是发布能力，Host 不能因此放弃本地的权限控制和审计；这些决策依赖 Host 持有的用户、租户、任务和审批上下文。Server 可额外保护自身资源，但其鉴权不能替代 Host Runtime 的治理门禁。

## Evidence

用户在 Week 2 第 3 课回答：远程 MCP Server 负责提供能力，权限和审计仍应由 MCP 发起方控制。
