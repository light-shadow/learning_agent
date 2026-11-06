"""项目长期记忆的持久化存储核心。

使用 Python 标准库 sqlite3，无第三方依赖。

存储模型：
  memories   主表，一条 (project, key) 一条活跃记录
  audit_log  审计日志，记录 write / read / update / delete / init

每条记忆包含：
  - project     项目名（按项目查找的索引维度）
  - key         记忆键（项目内唯一）
  - value       记忆内容（JSON 字符串）
  - source      来源（这条知识从哪里来）
  - scope       适用范围（默认 project）
  - status      失效状态：active / superseded / deleted
  - version     版本号（每次 update 自增）
  - created_at / updated_at  检查时间

记忆是“候选线索”，不是事实担保：调用方仍需与当前文件/代码核对。
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

# 允许的失效状态
ACTIVE = "active"
SUPERSEDED = "superseded"
DELETED = "deleted"
_VALID_STATUS = {ACTIVE, SUPERSEDED, DELETED}

# 校验 project / key 的字符，避免路径穿越与非法标识
_IDENT_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _now() -> str:
    """返回带时区的 ISO-8601 时间戳，作为“检查时间”。"""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _validate_ident(value: str, label: str) -> str:
    if not isinstance(value, str) or not _IDENT_RE.match(value):
        raise MemoryStoreError(
            f"{label} 必须是 1-128 位字母/数字/._- 组成的字符串，收到: {value!r}"
        )
    return value


class MemoryStoreError(Exception):
    """记忆存储的受检错误。"""


@dataclass
class MemoryRecord:
    """一条记忆记录的只读投影。"""

    project: str
    key: str
    value: dict
    source: str
    scope: str
    status: str
    version: int
    created_at: str
    updated_at: str

    @property
    def value_json(self) -> str:
        return json.dumps(self.value, ensure_ascii=False, indent=2)


class ProjectMemory:
    """按项目索引的长期记忆存储（SQLite 持久化）。"""

    def __init__(self, db_path: str):
        self.db_path = os.path.abspath(db_path)

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def init(self) -> str:
        """建库：创建表与索引，幂等。返回数据库绝对路径。"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    project    TEXT NOT NULL,
                    key        TEXT NOT NULL,
                    value      TEXT NOT NULL,
                    source     TEXT NOT NULL,
                    scope      TEXT NOT NULL DEFAULT 'project',
                    status     TEXT NOT NULL DEFAULT 'active',
                    version    INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(project, key)
                );
                CREATE INDEX IF NOT EXISTS idx_memories_project ON memories(project);
                CREATE INDEX IF NOT EXISTS idx_memories_status   ON memories(status);

                CREATE TABLE IF NOT EXISTS audit_log (
                    id     INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    project TEXT,
                    key    TEXT,
                    detail TEXT,
                    at     TEXT NOT NULL
                );
                """
            )
            self._audit(conn, "init", None, None, {"db": self.db_path})
        return self.db_path

    # ------------------------------------------------------------------
    # 四个动作
    # ------------------------------------------------------------------
    def write(
        self,
        project: str,
        key: str,
        value: dict,
        source: str,
        scope: str = "project",
    ) -> MemoryRecord:
        """写入一条新记忆。同 (project, key) 已存在时抛错，提示改用 update。"""
        project = _validate_ident(project, "project")
        key = _validate_ident(key, "key")
        if not isinstance(value, dict):
            raise MemoryStoreError("value 必须是 dict（JSON 对象）")
        if not isinstance(source, str) or not source.strip():
            raise MemoryStoreError("source（来源）不能为空")
        if not isinstance(scope, str) or not scope.strip():
            raise MemoryStoreError("scope（范围）不能为空")

        now = _now()
        with self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM memories WHERE project = ? AND key = ?",
                (project, key),
            ).fetchone()
            if exists:
                raise MemoryStoreError(
                    f"记忆已存在: project={project!r} key={key!r}，请使用 update"
                )
            conn.execute(
                """
                INSERT INTO memories
                    (project, key, value, source, scope, status, version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (project, key, json.dumps(value, ensure_ascii=False),
                 source, scope, ACTIVE, now, now),
            )
            self._audit(conn, "write", project, key, {"value": value, "source": source})
        return self._get(project, key)

    def read(
        self,
        project: str,
        key: Optional[str] = None,
        *,
        include_inactive: bool = False,
    ) -> list[MemoryRecord]:
        """按项目查找并读取记忆；可指定 key 精确读取。"""
        project = _validate_ident(project, "project")
        if key is not None:
            key = _validate_ident(key, "key")

        sql = "SELECT * FROM memories WHERE project = ?"
        params: list[Any] = [project]
        if key is not None:
            sql += " AND key = ?"
            params.append(key)
        if not include_inactive:
            sql += " AND status = 'active'"

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            self._audit(conn, "read", project, key, {"count": len(rows)})
        return [self._row_to_record(r) for r in rows]

    def update(
        self,
        project: str,
        key: str,
        value: dict,
        source: str,
        scope: Optional[str] = None,
    ) -> MemoryRecord:
        """更新已有记忆：版本 +1，记录旧值到审计日志。"""
        project = _validate_ident(project, "project")
        key = _validate_ident(key, "key")
        if not isinstance(value, dict):
            raise MemoryStoreError("value 必须是 dict（JSON 对象）")
        if not isinstance(source, str) or not source.strip():
            raise MemoryStoreError("source（来源）不能为空")

        now = _now()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memories WHERE project = ? AND key = ?",
                (project, key),
            ).fetchone()
            if row is None:
                raise MemoryStoreError(
                    f"记忆不存在: project={project!r} key={key!r}，请先 write"
                )
            old = self._row_to_record(row)
            new_scope = scope if scope else old.scope
            conn.execute(
                """
                UPDATE memories
                   SET value = ?, source = ?, scope = ?, status = 'active',
                       version = version + 1, updated_at = ?
                 WHERE project = ? AND key = ?
                """,
                (json.dumps(value, ensure_ascii=False), source, new_scope, now,
                 project, key),
            )
            self._audit(
                conn, "update", project, key,
                {"old": old.value, "new": value, "source": source},
            )
        return self._get(project, key)

    def delete(self, project: str, key: str, *, purge: bool = False) -> bool:
        """删除一条记忆。默认软删除（标记 deleted），purge=True 物理删除。"""
        project = _validate_ident(project, "project")
        key = _validate_ident(key, "key")
        now = _now()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM memories WHERE project = ? AND key = ?",
                (project, key),
            ).fetchone()
            if row is None:
                return False
            if purge:
                conn.execute(
                    "DELETE FROM memories WHERE project = ? AND key = ?",
                    (project, key),
                )
                self._audit(conn, "delete", project, key, {"purge": True, "at": now})
            else:
                conn.execute(
                    "UPDATE memories SET status = 'deleted', updated_at = ? "
                    "WHERE project = ? AND key = ?",
                    (now, project, key),
                )
                self._audit(conn, "delete", project, key, {"purge": False, "at": now})
        return True

    def list_projects(self) -> list[str]:
        """列出所有项目（索引）。"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT project FROM memories ORDER BY project"
            ).fetchall()
        return [r[0] for r in rows]

    def list_all(self) -> list[MemoryRecord]:
        """列出全部记忆（含失效记录），用于审计/调试。"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memories ORDER BY project, key"
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _audit(self, conn, action, project, key, detail) -> None:
        conn.execute(
            "INSERT INTO audit_log (action, project, key, detail, at) VALUES (?, ?, ?, ?, ?)",
            (action, project, key, json.dumps(detail, ensure_ascii=False, default=str), _now()),
        )

    def _get(self, project: str, key: str) -> MemoryRecord:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memories WHERE project = ? AND key = ?",
                (project, key),
            ).fetchone()
        if row is None:
            raise MemoryStoreError(f"记忆不存在: project={project!r} key={key!r}")
        return self._row_to_record(row)

    @staticmethod
    def _row_to_record(row) -> MemoryRecord:
        return MemoryRecord(
            project=row["project"],
            key=row["key"],
            value=json.loads(row["value"]),
            source=row["source"],
            scope=row["scope"],
            status=row["status"],
            version=row["version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
