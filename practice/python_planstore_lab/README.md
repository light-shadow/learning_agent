# Python PlanStore Lab

这是一个独立、零第三方依赖的 Python 实战：用可运行代码实现课程中的 Plan、Evidence、Completion Contract 与 `revise_plan`。

## 运行

在本目录执行：

```powershell
python -m unittest -v
```

或使用 Codex 附带 Python：

```powershell
& 'C:\Users\xuan\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest -v
```

## 本 Lab 已实现

- `PlanStore.start()`：仅依赖全部 `COMPLETED` 时允许开始。
- `PlanStore.record_evidence()`：模拟 Runtime 写入真实工具证据。
- `PlanStore.complete()`：检查证据存在、归属、版本新鲜性与成功标准。
- `PlanStore.block()`：记录权限、环境或人工决策导致的真实阻塞，且不满足下游依赖。
- `PlanStore.revise()`：在候选副本上替换步骤并原子重连下游依赖。
- `all_steps_completed_contract()`：示例任务级完成契约。
- 9 个确定性测试：覆盖未就绪、真实阻塞、缺证据、证据归属、旧证据、预期失败复现、修订重连、版本冲突和依赖环。

## 建议实践顺序

1. 先运行测试，阅读每个用例的中文名称和断言。
2. 在 `test_revision_rejects_cycle_without_mutating_plan` 中理解“候选副本 + 原子拒绝”。
3. 尝试新增 `resume(step_id)`，让人工解除阻塞后能在保留审计记录的前提下恢复执行。
4. 尝试新增 `fail(step_id, reason)`，区分可等待的外部阻塞与已确认的执行失败。
5. 尝试将 `all_steps_completed_contract` 改为只接受 s4 的三类测试证据和 s5 的交付文档证据。
6. 下一阶段再将 `PlanStore` 接入真正的 Tool Runtime；当前 Lab 只验证规则，不执行命令或修改业务代码。

## 本轮要回答的问题

- 为什么 s2 的预期失败可以完成“复现”步骤，但不能完成“修复验证”步骤？
- 为什么 `revise()` 要先复制 `Plan`，而不直接修改当前 `Plan`？
- 当前实现中，哪些地方仍是单进程内存模型的限制？

