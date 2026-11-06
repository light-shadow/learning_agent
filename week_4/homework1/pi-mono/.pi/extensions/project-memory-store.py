"""供 pi 扩展调用的本地项目记忆存储，输入输出均为 UTF-8 JSON。"""

import json
import os
import sqlite3
import sys


def run(request):
    """按项目绝对路径和记忆键执行写入、查询、更新或删除。"""
    db = os.path.abspath(os.environ.get("PI_MEMORY_DB", os.path.expanduser("~/.pi/agent/project-memory.sqlite3")))
    os.makedirs(os.path.dirname(db), exist_ok=True)
    project = os.path.normcase(os.path.realpath(request["project"]))
    action = request["action"]
    key = (request.get("key") or "").strip()
    if action not in ("write", "read", "update", "delete"):
        raise ValueError("不支持的动作")
    if action != "read" and not key:
        raise ValueError("此动作需要非空 key")
    if action in ("write", "update") and (not request.get("content", "").strip() or not request.get("source", "").strip()):
        raise ValueError("写入和更新需要非空 content 和 source")
    with sqlite3.connect(db, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE IF NOT EXISTS memories (project TEXT NOT NULL, key TEXT NOT NULL, content TEXT NOT NULL, source TEXT NOT NULL, version INTEGER NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(project, key))")
        if action == "write":
            conn.execute("INSERT INTO memories(project, key, content, source, version) VALUES (?, ?, ?, ?, 1)", (project, key, request["content"], request["source"]))
        elif action == "update":
            result = conn.execute("UPDATE memories SET content=?, source=?, version=version+1, updated_at=CURRENT_TIMESTAMP WHERE project=? AND key=?", (request["content"], request["source"], project, key))
            if result.rowcount == 0:
                raise ValueError("记忆不存在，无法更新")
        elif action == "delete":
            result = conn.execute("DELETE FROM memories WHERE project=? AND key=?", (project, key))
            if result.rowcount == 0:
                raise ValueError("记忆不存在，无法删除")
        rows = conn.execute("SELECT * FROM memories WHERE project=?" + (" AND key=?" if key else "") + " ORDER BY key", (project, key) if key else (project,)).fetchall()
    return {"database": db, "project": project, "action": action, "records": [dict(row) for row in rows]}


if __name__ == "__main__":
    try:
        print(json.dumps(run(json.load(sys.stdin)), ensure_ascii=False))
    except (ValueError, KeyError, sqlite3.Error, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
