"""真实迁移会话测试，分进程验证记忆，并保留原始结果作为截图数据。"""
import html
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent.parent / "login_demo"
OUT = ROOT / "memory-evidence"
DB = OUT / "project-memory.sqlite3"
OLD = PROJECT / "tests" / "test_session.py"
NEW = PROJECT / "tests" / "auth" / "test_session.py"
GUIDE = PROJECT / "artifacts" / "test-guide.md"


def tool(action, content=None, source=None):
    """在全新的 Node 进程中调用扩展并读取其 JSON 结果。"""
    request = {"action": action, "key": "session-test", "content": content, "source": source}
    env = {**os.environ, "PI_MEMORY_DB": str(DB)}
    result = subprocess.run(["node", str(ROOT / "memory-tool-runner.mjs"), json.dumps(request)], cwd=ROOT, env=env, text=True, encoding="utf-8", capture_output=True, check=True)
    return json.loads(result.stdout)


def run_test(module):
    """在项目目录运行指定的会话测试，失败时中止验证。"""
    result = subprocess.run([sys.executable, "-m", "unittest", module, "-v"], cwd=PROJECT, text=True, encoding="utf-8", capture_output=True)
    output = result.stdout + result.stderr
    if result.returncode:
        raise RuntimeError(output)
    return output


def report(number, title, lines):
    """保存真实执行结果及可供浏览器截图的报告页面。"""
    text = "\n".join(lines)
    (OUT / f"{number}.txt").write_text(text + "\n", encoding="utf-8")
    page = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>body{{margin:0;background:#f2f5fa;color:#17243a;font:19px 'Microsoft YaHei',sans-serif}}main{{margin:40px auto;padding:38px 46px;max-width:1300px;background:white;border-radius:12px;box-shadow:0 4px 24px #c7d0dd}}h1{{font-size:30px;margin:0 0 22px}}pre{{font:18px/1.65 Consolas,'Microsoft YaHei',monospace;white-space:pre-wrap;overflow-wrap:anywhere}}small{{color:#53657c}}</style>
<main><h1>{html.escape(title)}</h1><small>实际命令输出记录 · 通过 pi 扩展工具执行 · 独立进程</small><pre>{html.escape(text)}</pre></main></html>"""
    (OUT / f"{number}.html").write_text(page, encoding="utf-8")


def main():
    """迁到旧路径、持久化并读取，再迁回新路径并按实际测试结果更新。"""
    OUT.mkdir(exist_ok=True)
    if DB.exists():
        raise RuntimeError(f"验证数据库已存在，请指定新的输出目录：{DB}")
    if not OLD.is_file() or not NEW.is_file():
        raise RuntimeError("预期的旧路径指引或新路径测试不存在")
    old_stub = OLD.read_bytes()
    original_test = NEW.read_bytes()
    original_guide = GUIDE.read_bytes()
    try:
        OLD.write_bytes(original_test.replace(b"tests.auth.test_session", b"tests.test_session"))
        NEW.unlink()
        GUIDE.write_bytes(original_guide.replace(b"tests/auth/test_session.py", b"tests/test_session.py").replace(b"tests.auth.test_session", b"tests.test_session"))
        old_output = run_test("tests.test_session")
        old_content = "测试路径：tests/test_session.py；运行命令：python -m unittest tests.test_session -v；实际结果：5 tests OK。"
        written = tool("write", old_content, "artifacts/test-guide.md; tests/test_session.py")
        report("01-build", "01 建库并写入旧测试入口", [f"数据库：{written['database']}", "真实迁移：tests/auth/test_session.py → tests/test_session.py", "测试命令：python -m unittest tests.test_session -v", old_output.strip(), "写入结果：" + json.dumps(written["records"][0], ensure_ascii=False)])
        recalled = tool("read")
        record = recalled["records"][0]
        assert "tests/test_session.py" in record["content"] and OLD.is_file() and not NEW.exists()
        report("02-read", "02 新进程查询、核对与回答", ["读取进程：新启动的 Node 进程（加载同一 pi 扩展）", "数据库：" + recalled["database"], "记忆：" + record["content"], "来源：" + record["source"], f"核对：tests/test_session.py 存在 = {OLD.is_file()}", f"核对：tests/auth/test_session.py 存在 = {NEW.exists()}", "回答：当前会话测试入口是 tests/test_session.py。"])
        NEW.write_bytes(OLD.read_bytes().replace(b"tests.test_session", b"tests.auth.test_session"))
        OLD.write_bytes(old_stub)
        GUIDE.write_bytes(original_guide)
        new_output = run_test("tests.auth.test_session")
        new_content = "测试路径：tests/auth/test_session.py；运行命令：python -m unittest tests.auth.test_session -v；实际结果：5 tests OK。"
        updated = tool("update", new_content, "artifacts/test-guide.md; tests/auth/test_session.py")
        final = tool("read")["records"][0]
        assert final["content"] == new_content and final["version"] == 2
        report("03-update", "03 迁回并更新后的回答", ["真实迁回：tests/test_session.py → tests/auth/test_session.py", "测试命令：python -m unittest tests.auth.test_session -v", new_output.strip(), "更新后记忆：" + final["content"], "来源：" + final["source"], f"版本：{final['version']}；测试文件存在：{NEW.is_file()}", "回答：当前会话测试入口已更新为 tests/auth/test_session.py。"])
        print(f"验证完成；数据库和证据：{OUT}")
    finally:
        OLD.write_bytes(old_stub)
        NEW.write_bytes(original_test)
        GUIDE.write_bytes(original_guide)


if __name__ == "__main__":
    main()
