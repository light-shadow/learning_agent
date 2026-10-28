# 已掌握证据不可变与步骤状态可变

用户能正确区分：Evidence 初始化后不允许修改，以保证其作为历史事实可追溯；PlanStep 则需要随执行过程发生状态变化。这为理解 PlanStore 的证据门禁与状态转换边界建立了基础。

## Evidence

用户在逐行讲解 PlanStore 的检索问题中回答“Evidence 初始化之后不允许修改，PlanStep 有状态的变化”。
