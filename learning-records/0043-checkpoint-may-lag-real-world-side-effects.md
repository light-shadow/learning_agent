# 已掌握 Checkpoint 可能落后于真实副作用

用户能判断 Checkpoint 标记补丁未写入时，恢复仍须先核对工作区，因为补丁可能已经落盘但尚未来得及写入 Checkpoint。Checkpoint 是历史记录而非当前现场证明；直接续跑可能重复写入或覆盖真实状态。

## Evidence

用户在 Week 3 第 3 课回答：可能补丁已写入，但还没来得及写入 Checkpoint。
