"""通过独立进程验证 pi 项目记忆，并记录当前项目的真实测试入口。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent.parent / "login_demo"
STORE = ROOT / ".pi" / "extensions" / "project-memory-store.py"
DB = ROOT / "project-memory.sqlite3"


def call(db, action, key=None, content=None, source=None, project=PROJECT):
    """启动独立存储进程并返回持久化操作结果。"""
    env = {**os.environ, "PI_MEMORY_DB": str(db), "PYTHONIOENCODING": "utf-8"}
    request = {"action": action, "project": str(project), "key": key, "content": content, "source": source}
    result = subprocess.run([sys.executable, str(STORE)], input=json.dumps(request), text=True, encoding="utf-8", capture_output=True, env=env)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout)


def main():
    """检验增删改查与项目隔离，然后保存当前会话测试信息。"""
    with tempfile.TemporaryDirectory(dir=ROOT) as directory:
        test_db = Path(directory) / "test.sqlite3"
        call(test_db, "write", "key", "first", "source")
        assert call(test_db, "read", "key")["records"][0]["content"] == "first"
        assert not call(test_db, "read", project=ROOT)["records"]
        assert call(test_db, "update", "key", "second", "source")["records"][0]["version"] == 2
        call(test_db, "delete", "key")
        assert not call(test_db, "read", "key")["records"]
    print("独立进程增删改查及项目隔离：通过")
    guide = (PROJECT / "artifacts" / "test-guide.md").read_text(encoding="utf-8")
    test = PROJECT / "tests" / "auth" / "test_session.py"
    assert "tests/auth/test_session.py" in guide and test.is_file()
    command = [sys.executable, "-m", "unittest", "tests.auth.test_session", "-v"]
    result = subprocess.run(command, cwd=PROJECT, text=True, encoding="utf-8", capture_output=True)
    print(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError("会话测试失败，未更新记忆")
    source = "artifacts/test-guide.md; tests/auth/test_session.py"
    content = "测试路径：tests/auth/test_session.py；运行命令：python -m unittest tests.auth.test_session -v；实际结果：5 tests OK。"
    existing = call(DB, "read", "session-test")["records"]
    saved = call(DB, "update" if existing else "write", "session-test", content, source)
    print("保存结果：", json.dumps(saved, ensure_ascii=False))
    print("全新进程读取：", json.dumps(call(DB, "read", "session-test"), ensure_ascii=False))
    print("核对测试文件存在：", test.is_file())


if __name__ == "__main__":
    main()
