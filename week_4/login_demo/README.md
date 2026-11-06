# Login Demo

## 关键文件

- `src/routes/login.ts`: 登录入口，`POST /api/login`
- `src/services/auth-service.ts`: 登录业务逻辑
- `src/repositories/user-repository.ts`: 用户查询
- `src/db/database.ts`: 模拟数据库访问，明确访问 `users` 表
- `src/middleware/auth-middleware.ts`: 认证中间件
- `src/utils/password.ts`: 密码校验
- `src/utils/token.ts`: token 签发与校验

## 项目长期记忆（week4 作业）

为 pi 增加的项目长期记忆，支持四个动作：写入、按项目查找并读取、更新、删除。
持久化使用 SQLite（Python 标准库，无第三方依赖），每条记忆带来源、范围、失效状态、
版本号与审计日志。

- `memory/store.py`: 记忆存储核心（`ProjectMemory`：write / read / update / delete / list）
- `memory/cli.py`: 命令行入口 `python -m memory <命令>`
- `demo.py`: 三步端到端演示（建库写入 → 全新会话读取核对 → 迁移后更新）
- `artifacts/test-guide.md`: 会话测试说明（记忆的“来源”）
- `tests/auth/test_session.py`: 会话测试（登录会话 token 契约）

### 运行方式

```bash
# 记忆库默认放在工作区根 .pi-memory/memory.db（可用 PI_MEMORY_DB 或 --db 覆盖）
python demo.py step1   # 建库 + 写入初始记忆
python demo.py step2   # 全新会话读取 + 核对文件
python demo.py step3   # 运行新测试命令 + 更新记忆

# 或直接使用 CLI
python -m memory init
python -m memory write --project login_demo --key session-test --value-file v.json --source "..."
python -m memory read  --project login_demo
python -m memory update --project login_demo --key session-test --value-file v.json --source "..."
python -m memory delete --project login_demo --key session-test
```
