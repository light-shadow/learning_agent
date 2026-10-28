# 已掌握 Gateway 集中治理供应商关切

用户能判断若各 Agent 自行保存 Provider Key、拼接 Base URL 和实现重试，会产生重复工作与实现漂移；收敛至 Gateway 后，各 Agent 可通过统一接口调用模型，无需感知厂商细节。该边界也支持集中执行模型切换、密钥轮换、限流和观测策略。

## Evidence

用户在 Week 1 第 5 课回答：各 Agent 自行实现会重复；Gateway 统一维护后，Agent 可直接接入而不关注厂商内部细节。
