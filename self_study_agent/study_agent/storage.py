"""SQLite 学习数据与审计存储。"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .models import ConceptDraft, QuestionDraft, QuestionType, SourceChunk, SourceType
from .readers import ExtractedSource


class StudyStore:
    """保存资料、题库、作答、掌握度和审计事件。"""

    def __init__(self, database_path: Path) -> None:
        """初始化数据库文件和表结构。"""
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._create_tables()

    def close(self) -> None:
        """关闭 SQLite 连接。"""
        self._connection.close()

    def add_source(self, source: ExtractedSource) -> tuple[str, bool]:
        """保存资料和文本块；相同内容哈希复用已有资料。"""
        existing = self._connection.execute(
            "SELECT source_id FROM sources WHERE content_hash = ?", (source.content_hash,)
        ).fetchone()
        if existing:
            with self._connection:
                self._connection.execute(
                    "UPDATE sources SET title = ? WHERE source_id = ?",
                    (source.title, existing["source_id"]),
                )
            return str(existing["source_id"]), False
        source_id = self._new_id("src")
        now = self._now()
        with self._connection:
            self._connection.execute(
                """INSERT INTO sources(source_id, source_type, locator, title, content_hash, normalized_text, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (source_id, source.source_type.value, source.locator, source.title, source.content_hash,
                 source.normalized_text, now),
            )
            self._insert_chunks(source_id, source.chunks)
        return source_id, True

    def list_sources(self) -> list[dict[str, Any]]:
        """返回资料摘要，避免 CLI 默认输出完整正文。"""
        rows = self._connection.execute(
            """SELECT source_id, source_type, locator, title, content_hash, created_at,
                      (SELECT COUNT(*) FROM source_chunks c WHERE c.source_id = s.source_id) AS chunk_count
               FROM sources s ORDER BY created_at DESC"""
        ).fetchall()
        return [dict(row) for row in rows]

    def get_source(self, source_id: str) -> dict[str, Any] | None:
        """读取资料元数据和规范化文本，用于知识提炼。"""
        row = self._connection.execute("SELECT * FROM sources WHERE source_id = ?", (source_id,)).fetchone()
        return dict(row) if row else None

    def get_chunks(self, source_id: str) -> list[dict[str, Any]]:
        """按稳定顺序读取资料文本块。"""
        rows = self._connection.execute(
            "SELECT chunk_id, chunk_index, text FROM source_chunks WHERE source_id = ? ORDER BY chunk_index",
            (source_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def replace_concepts(self, source_id: str, concepts: list[ConceptDraft]) -> list[str]:
        """替换尚未关联作答的知识点，并保留稳定来源关系。"""
        with self._connection:
            self._connection.execute(
                """DELETE FROM attempts WHERE question_id IN (
                       SELECT q.question_id FROM questions q JOIN concepts c ON c.concept_id = q.concept_id
                       WHERE c.source_id = ?
                   )""",
                (source_id,),
            )
            self._connection.execute(
                """DELETE FROM questions WHERE concept_id IN (
                       SELECT concept_id FROM concepts WHERE source_id = ?
                   )""",
                (source_id,),
            )
            self._connection.execute("DELETE FROM mastery WHERE concept_id IN (SELECT concept_id FROM concepts WHERE source_id = ?)", (source_id,))
            self._connection.execute("DELETE FROM concepts WHERE source_id = ?", (source_id,))
            ids: list[str] = []
            for concept in concepts:
                concept_id = self._new_id("con")
                ids.append(concept_id)
                self._connection.execute(
                    """INSERT INTO concepts(concept_id, source_id, chunk_index, title, summary, keywords_json, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (concept_id, source_id, concept.chunk_index, concept.title, concept.summary,
                     json.dumps(concept.keywords, ensure_ascii=False), self._now()),
                )
        return ids

    def list_concepts(self, source_id: str | None = None) -> list[dict[str, Any]]:
        """返回知识点及其文本块引用。"""
        sql = "SELECT * FROM concepts"
        params: tuple[Any, ...] = ()
        if source_id:
            sql += " WHERE source_id = ?"
            params = (source_id,)
        rows = self._connection.execute(sql + " ORDER BY created_at, chunk_index", params).fetchall()
        result = [dict(row) for row in rows]
        for item in result:
            item["keywords"] = json.loads(item.pop("keywords_json"))
        return result

    def add_questions(self, questions: list[QuestionDraft]) -> list[str]:
        """将已通过题目契约校验的题目写入题库。"""
        question_ids: list[str] = []
        with self._connection:
            for question in questions:
                question_id = self._new_id("q")
                question_ids.append(question_id)
                self._connection.execute(
                    """INSERT INTO questions(question_id, concept_id, question_type, prompt, options_json, answer,
                                                 explanation, source_refs_json, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (question_id, question.concept_id, question.question_type.value, question.prompt,
                     json.dumps(question.options, ensure_ascii=False), question.answer, question.explanation,
                     json.dumps(question.source_refs, ensure_ascii=False), self._now()),
                )
        return question_ids

    def select_questions(self, learner_id: str, source_id: str | None, count: int) -> list[dict[str, Any]]:
        """按掌握度、最近错误和未覆盖状态选择下一轮练习。"""
        sql = """
            SELECT q.*, c.source_id, c.title AS concept_title,
                   COALESCE(m.mastery, 0.5) AS mastery,
                   COALESCE(m.last_answered_at, '') AS last_answered_at
            FROM questions q
            JOIN concepts c ON c.concept_id = q.concept_id
            LEFT JOIN mastery m ON m.concept_id = c.concept_id AND m.learner_id = ?
        """
        params: list[Any] = [learner_id]
        if source_id:
            sql += " WHERE c.source_id = ?"
            params.append(source_id)
        sql += " ORDER BY mastery ASC, last_answered_at ASC, q.created_at ASC LIMIT ?"
        params.append(count)
        rows = self._connection.execute(sql, tuple(params)).fetchall()
        return [self._decode_question(dict(row)) for row in rows]

    def get_question(self, question_id: str) -> dict[str, Any] | None:
        """读取题目答案与讲解，供 Runtime 评分使用。"""
        row = self._connection.execute("SELECT * FROM questions WHERE question_id = ?", (question_id,)).fetchone()
        return self._decode_question(dict(row)) if row else None

    def save_attempt(
        self,
        learner_id: str,
        question: dict[str, Any],
        answer: str,
        score: float | None,
        status: str,
        feedback: str,
    ) -> float | None:
        """保存作答并按分数更新所属知识点掌握度。"""
        attempt_id = self._new_id("att")
        now = self._now()
        mastery: float | None = None
        with self._connection:
            self._connection.execute(
                """INSERT INTO attempts(attempt_id, learner_id, question_id, answer, score, status, feedback, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (attempt_id, learner_id, question["question_id"], answer, score, status, feedback, now),
            )
            if score is not None:
                row = self._connection.execute(
                    "SELECT mastery FROM mastery WHERE learner_id = ? AND concept_id = ?",
                    (learner_id, question["concept_id"]),
                ).fetchone()
                previous = float(row["mastery"]) if row else 0.5
                mastery = max(0.0, min(1.0, previous + (score - 0.5) * 0.3))
                self._connection.execute(
                    """INSERT INTO mastery(learner_id, concept_id, mastery, last_answered_at)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(learner_id, concept_id) DO UPDATE SET
                         mastery=excluded.mastery, last_answered_at=excluded.last_answered_at""",
                    (learner_id, question["concept_id"], mastery, now),
                )
        return mastery

    def review(self, learner_id: str) -> list[dict[str, Any]]:
        """返回按薄弱程度排序的掌握度概览。"""
        rows = self._connection.execute(
            """SELECT c.concept_id, c.title, c.summary, COALESCE(m.mastery, 0.5) AS mastery,
                      m.last_answered_at
               FROM concepts c LEFT JOIN mastery m
                 ON m.concept_id = c.concept_id AND m.learner_id = ?
               ORDER BY mastery ASC, m.last_answered_at ASC""",
            (learner_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_attempt_history(self, learner_id: str, source_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """读取指定 PDF 下该学习者已经提交的答题记录，按最新作答时间倒序返回。"""
        rows = self._connection.execute(
            """SELECT a.attempt_id, a.question_id, a.answer, a.score, a.status, a.feedback, a.created_at,
                      q.question_type, q.prompt, c.title AS concept_title
               FROM attempts a
               JOIN questions q ON q.question_id = a.question_id
               JOIN concepts c ON c.concept_id = q.concept_id
               WHERE a.learner_id = ? AND c.source_id = ?
               ORDER BY a.created_at DESC
               LIMIT ?""",
            (learner_id, source_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def add_audit(self, tool_call_id: str, tool_name: str, code: str, argument_keys: list[str], source_refs: list[str]) -> None:
        """记录最小审计信息，不保存资料原文、模型提示词或密钥。"""
        with self._connection:
            self._connection.execute(
                """INSERT INTO audit_events(event_id, tool_call_id, tool_name, code, argument_keys_json,
                                              source_refs_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (self._new_id("audit"), tool_call_id, tool_name, code,
                 json.dumps(sorted(argument_keys)), json.dumps(source_refs), self._now()),
            )

    def list_audit(self) -> list[dict[str, Any]]:
        """读取审计摘要，供 CLI 排查统一执行链路。"""
        rows = self._connection.execute("SELECT * FROM audit_events ORDER BY created_at").fetchall()
        return [dict(row) for row in rows]

    def _insert_chunks(self, source_id: str, chunks: list[SourceChunk]) -> None:
        """批量保存资料文本块。"""
        for chunk in chunks:
            self._connection.execute(
                "INSERT INTO source_chunks(chunk_id, source_id, chunk_index, text) VALUES (?, ?, ?, ?)",
                (self._new_id("chk"), source_id, chunk.chunk_index, chunk.text),
            )

    def _create_tables(self) -> None:
        """创建首版所需的 SQLite 表。"""
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS sources (
                source_id TEXT PRIMARY KEY, source_type TEXT NOT NULL, locator TEXT NOT NULL,
                title TEXT NOT NULL, content_hash TEXT NOT NULL UNIQUE, normalized_text TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS source_chunks (
                chunk_id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
                chunk_index INTEGER NOT NULL, text TEXT NOT NULL, UNIQUE(source_id, chunk_index)
            );
            CREATE TABLE IF NOT EXISTS concepts (
                concept_id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
                chunk_index INTEGER NOT NULL, title TEXT NOT NULL, summary TEXT NOT NULL,
                keywords_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS questions (
                question_id TEXT PRIMARY KEY, concept_id TEXT NOT NULL REFERENCES concepts(concept_id) ON DELETE CASCADE,
                question_type TEXT NOT NULL, prompt TEXT NOT NULL, options_json TEXT NOT NULL, answer TEXT NOT NULL,
                explanation TEXT NOT NULL, source_refs_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS attempts (
                attempt_id TEXT PRIMARY KEY, learner_id TEXT NOT NULL, question_id TEXT NOT NULL REFERENCES questions(question_id),
                answer TEXT NOT NULL, score REAL, status TEXT NOT NULL, feedback TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS mastery (
                learner_id TEXT NOT NULL, concept_id TEXT NOT NULL REFERENCES concepts(concept_id), mastery REAL NOT NULL,
                last_answered_at TEXT NOT NULL, PRIMARY KEY(learner_id, concept_id)
            );
            CREATE TABLE IF NOT EXISTS audit_events (
                event_id TEXT PRIMARY KEY, tool_call_id TEXT NOT NULL, tool_name TEXT NOT NULL, code TEXT NOT NULL,
                argument_keys_json TEXT NOT NULL, source_refs_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            """
        )
        self._connection.commit()

    @staticmethod
    def _decode_question(question: dict[str, Any]) -> dict[str, Any]:
        """还原 SQLite 保存的 JSON 字段。"""
        question["options"] = json.loads(question.pop("options_json"))
        question["source_refs"] = json.loads(question.pop("source_refs_json"))
        return question

    @staticmethod
    def _new_id(prefix: str) -> str:
        """生成可在审计中追踪的本地标识。"""
        return f"{prefix}_{uuid4().hex}"

    @staticmethod
    def _now() -> str:
        """生成统一 UTC 时间戳。"""
        return datetime.now(UTC).isoformat()
