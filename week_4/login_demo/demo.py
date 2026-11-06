"""login_demo 项目长期记忆的端到端演示。

三个步骤分别对应三张截图，每一步都是独立进程（模拟“关闭会话、开启全新会话”）：

  python demo.py step1   建库 + 写入初始记忆（返回实际保存路径）
  python demo.py step2   全新会话按项目读取 + 核对文件是否存在
  python demo.py step3   迁移后运行新测试命令 + 更新记忆

记忆库默认放在工作区根 ``.pi-memory/memory.db``（沙箱内 ``~`` 目录不可写），
可用环境变量 ``PI_MEMORY_DB`` 或 ``--db`` 覆盖。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from memory.store import ProjectMemory  # noqa: E402

# login_demo 根目录
HERE = os.path.dirname(os.path.abspath(__file__))
# 工作区根（login_demo 上三级：week_4 -> learning_agent -> agent_fullstack_geek）
WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
GUIDE = os.path.join(HERE, "artifacts", "test-guide.md")

PROJECT = "login_demo"
KEY = "session-test"


def db_path() -> str:
    env = os.environ.get("PI_MEMORY_DB")
    if env:
        return os.path.abspath(env)
    return os.path.join(WORKSPACE_ROOT, ".pi-memory", "memory.db")


def parse_test_guide(path: str = GUIDE) -> dict:
    """从测试说明中解析测试文件路径与运行命令。"""
    text = open(path, encoding="utf-8").read()
    m_test = re.search(r"测试文件：`(.+?)`", text)
    m_cmd = re.search(r"运行命令：`(.+?)`", text)
    if not m_test or not m_cmd:
        raise SystemExit(f"无法解析测试说明: {path}")
    return {"test_path": m_test.group(1), "run_command": m_cmd.group(1)}


def step1(db: str) -> None:
    print("=" * 62)
    print("步骤 1 / 3：建库并把会话测试入口写入长期记忆")
    print("=" * 62)
    mem = ProjectMemory(db)
    path = mem.init()
    print(f"[建库] 持久化存储已创建: {path}")

    info = parse_test_guide()
    test_path = info["test_path"]
    run_command = info["run_command"]
    exists = os.path.exists(os.path.join(HERE, test_path))
    print(f"[读取] 会话测试文件: {test_path}  (存在: {exists})")
    print(f"[读取] 测试说明运行命令: {run_command}")
    print(f"[读取] 测试说明来源: {GUIDE}")

    value = {
        "topic": "会话测试入口",
        "test_path": test_path,
        "run_command": run_command,
        "instructions": "artifacts/test-guide.md",
    }
    source = f"artifacts/test-guide.md + {test_path}"
    rec = mem.write(PROJECT, KEY, value, source)
    print(f"[写入] {rec.project}/{rec.key}  v{rec.version}  status={rec.status}")
    print(f"[写入] 来源: {source}")
    print(f"[返回] 实际保存路径: {path}")


def step2(db: str) -> None:
    print("=" * 62)
    print("步骤 2 / 3：全新会话按项目读取并核对记忆")
    print("=" * 62)
    mem = ProjectMemory(db)  # 新实例 + 新进程，等价于全新会话
    recs = mem.read(PROJECT, KEY)
    if not recs:
        print(f"[读取] 项目 {PROJECT!r} 中未找到 {KEY!r} 的记忆")
        return
    rec = recs[0]
    print(f"[读取] 命中记忆: {rec.project}/{rec.key}  v{rec.version}")
    print(f"        来源: {rec.source}")
    print(f"        测试路径: {rec.value['test_path']}")
    print(f"        运行命令: {rec.value['run_command']}")
    test_path = rec.value["test_path"]
    exists = os.path.exists(os.path.join(HERE, test_path))
    print(f"[核对] 记忆中的文件 {test_path} 当前是否存在: {exists}")
    print("[结论] " + ("一致：记忆与磁盘文件相符。" if exists
                       else "不一致：记忆指向的文件已失效，需要更新。"))


def step3(db: str) -> None:
    print("=" * 62)
    print("步骤 3 / 3：项目变化后运行新命令并更新记忆")
    print("=" * 62)
    info = parse_test_guide()
    test_path = info["test_path"]
    run_command = info["run_command"]
    print(f"[变化] 会话测试已迁移到: {test_path}")
    print(f"[变化] 新运行命令: {run_command}")

    # 运行新测试命令，捕获实际结果
    argv = shlex.split(run_command)
    result = subprocess.run(argv, cwd=HERE, capture_output=True, text=True)
    ok = result.returncode == 0
    lines = (result.stdout or result.stderr).strip().splitlines()
    ran = next((l for l in lines if l.startswith("Ran ")), None)
    summary = f"{ran}; {lines[-1]}" if ran and lines else (lines[-1] if lines else f"exit {result.returncode}")
    print(f"[运行] {run_command}")
    print(f"[运行] 实际结果: {summary}")

    mem = ProjectMemory(db)
    old = mem.read(PROJECT, KEY)
    old_path = old[0].value["test_path"] if old else None
    value = {
        "topic": "会话测试入口",
        "test_path": test_path,
        "run_command": run_command,
        "instructions": "artifacts/test-guide.md",
        "last_run": "PASSED" if ok else "FAILED",
    }
    source = f"artifacts/test-guide.md + {test_path}"
    rec = mem.update(PROJECT, KEY, value, source)
    print(f"[更新] 旧测试路径: {old_path}")
    print(f"[更新] 新测试路径: {rec.value['test_path']}")
    print(f"[更新] 版本号: v{rec.version}  (来源: {rec.source})")
    print(f"[返回] 实际保存路径: {db}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python demo.py")
    p.add_argument("step", choices=["step1", "step2", "step3"])
    p.add_argument("--db", default=None)
    args = p.parse_args(argv)
    db = db_path() if not args.db else os.path.abspath(args.db)

    if args.step == "step1":
        step1(db)
    elif args.step == "step2":
        step2(db)
    elif args.step == "step3":
        step3(db)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
