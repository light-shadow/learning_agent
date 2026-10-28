# 已掌握 Gateway 与 Agent Harness 的职责分界

用户能判断 Tool Runtime、Agent Loop 和任务状态机是各 Agent 的业务定制逻辑；若下沉到 Gateway，会削弱 Gateway 的通用复用能力并混淆职责。Gateway 应专注提供可治理的模型能力，这三类任务语义应由 Agent Harness 负责。

## Evidence

用户在 Week 1 第 6 课回答：不同 Agent 的三类逻辑可能不同且更业务化；Gateway 不应关注它们，应由 Agent Harness 负责。
