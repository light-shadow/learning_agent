# pi 项目长期记忆

从任意项目启动 pi 时使用本扩展的绝对路径，例如：

```powershell
cd H:\agent_fullstack_geek\learning_agent\week_4\login_demo
$env:TSX_TSCONFIG_PATH = 'H:\agent_fullstack_geek\learning_agent\week_4\homework1\pi-mono\tsconfig.json'
$env:PI_MEMORY_DB = 'H:\agent_fullstack_geek\learning_agent\week_4\homework1\pi-mono\project-memory.sqlite3'
H:\agent_fullstack_geek\learning_agent\week_4\homework1\pi-mono\pi-test.ps1 -e H:\agent_fullstack_geek\learning_agent\week_4\homework1\pi-mono\.pi\extensions\project-memory.ts
```

需先在 pi-mono 运行 `npm install --ignore-scripts`，并安装 Python 3。工具 `project_memory` 支持 `write`、`read`、`update`、`delete`；写入和更新需要 `key`、`content`、`source`，读取可省略 `key` 以查找当前项目所有记录。默认以启动目录的规范化绝对路径区分项目，也可通过 `project` 指定项目目录。写入已存在的键会报错，更新和删除不存在的键也会报错。

SQLite 默认位于 `~/.pi/agent/project-memory.sqlite3`，可使用 `PI_MEMORY_DB` 指定其他路径，工具结果会返回实际路径。使用 `PI_MEMORY_PYTHON` 可指定 Python 可执行文件。记忆只提供线索，使用前应核对来源及当前文件。删除为物理删除。

可运行 `python verify-project-memory.py` 检查存储层并保存当前测试入口，再运行 `node verify-extension.mjs` 检查扩展加载和读取。`verify-project-memory.py` 会写入或更新本目录的 `project-memory.sqlite3`。

验证时先将测试迁到 `tests/test_session.py`，更新说明并写入旧入口；随后迁回 `tests/auth/test_session.py`，恢复说明、运行测试并更新记忆。两个位置的测试各有 5 项通过。该测试是 Python 对 token 契约的镜像，不直接调用 TypeScript 实现。

三阶段的截图、原始输出和独立验证数据库位于 `memory-evidence/`。截图是由真实工具及测试输出生成的报告页面，不是 pi 对话界面截图；读取通过新启动的 Node 进程加载 pi 扩展实现，并非新的 pi 对话会话。`migration-verification.py` 是本次操作的验证脚本，会检查目标数据库是否已存在并在结束时恢复测试及说明文件。
