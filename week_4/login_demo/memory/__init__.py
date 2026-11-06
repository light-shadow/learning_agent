"""pi 的项目长期记忆（Project Long-term Memory）。

提供跨会话、按项目索引的持久化知识存储，支持四个动作：
  - write  写入
  - read   按项目查找并读取
  - update 更新
  - delete 删除

设计要点（对应课程 4.3 Memory 体系）：
  - 每条记忆都带来源（source）、适用范围（scope）、失效状态（status）；
  - 每次变更都写入审计日志（audit_log），并保留版本号（version）；
  - 记忆只是“候选线索”，不替代对当前代码/文件的现场核对。
"""

from .store import ProjectMemory, MemoryRecord, MemoryStoreError

__all__ = ["ProjectMemory", "MemoryRecord", "MemoryStoreError"]
