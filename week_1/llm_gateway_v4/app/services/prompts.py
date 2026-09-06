"""静态 v3 模板与 SQLite 版本化 Prompt 管理。"""
from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from app.core.errors import GatewayError
from app.schemas import Message, PromptCreate, PromptSelection, TemplateReference

LEGACY_TEMPLATES = {
    "summarize": {"default": "v1", "versions": {"v1": "请简要概括以下内容：\n{{text}}", "v2": "请用三句话概括以下文本：\n{{text}}"}},
    "translate": {"default": "v1", "versions": {"v1": "将以下内容翻译成{{target_lang}}：\n{{text}}"}},
}
STATIC_PROMPTS = {("knowledge_decision", "v1"): "你是${product_name}的知识库决策器。资料不足时搜索，资料充分时结束回答。不得编造制度内容。"}


class PromptRepository:
    """使用 SQLite 保存 Prompt 版本，并用受限模板渲染变量。"""

    def __init__(self, database_path: str) -> None:
        self.database_path = database_path
        self._lock = Lock()
        try:
            from jinja2 import StrictUndefined
            from jinja2.sandbox import SandboxedEnvironment
            self._jinja = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False)
        except ImportError:
            self._jinja = None

    def initialize(self) -> None:
        """创建 Prompt 表及激活版本查询索引。"""
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS prompts (id TEXT NOT NULL, version INTEGER NOT NULL, name TEXT NOT NULL, description TEXT, role TEXT NOT NULL, content TEXT NOT NULL, is_active INTEGER NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(id, version))")
            db.execute("CREATE INDEX IF NOT EXISTS idx_prompts_active ON prompts(id, is_active)")

    def create_version(self, prompt: PromptCreate) -> dict[str, Any]:
        """为同一 Prompt ID 新增递增版本，并可将其设为激活版本。"""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as db:
            version = int(db.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM prompts WHERE id = ?", (prompt.id,)).fetchone()[0])
            if prompt.activate:
                db.execute("UPDATE prompts SET is_active = 0 WHERE id = ?", (prompt.id,))
            db.execute("INSERT INTO prompts VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (prompt.id, version, prompt.name, prompt.description, prompt.role, prompt.content, int(prompt.activate), now))
        return {"id": prompt.id, "version": version, "name": prompt.name, "description": prompt.description, "role": prompt.role, "content": prompt.content, "is_active": prompt.activate, "created_at": now}

    def get(self, prompt_id: str, version: int | None = None) -> dict[str, Any]:
        """读取指定版本或当前激活版本的 Prompt。"""
        query, params = ("SELECT * FROM prompts WHERE id = ? AND version = ?", (prompt_id, version)) if version else ("SELECT * FROM prompts WHERE id = ? AND is_active = 1 ORDER BY version DESC LIMIT 1", (prompt_id,))
        with self._connect() as db:
            row = db.execute(query, params).fetchone()
        if row is None:
            raise GatewayError("Prompt 不存在", status_code=404, code="prompt_not_found", error_type="invalid_request_error")
        return dict(row)

    def list(self) -> list[dict[str, Any]]:
        """按 ID 和版本倒序返回所有持久化 Prompt。"""
        with self._connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM prompts ORDER BY id, version DESC").fetchall()]

    def render(self, prompt_id: str, variables: dict[str, Any], version: int | None = None) -> tuple[dict[str, Any], str]:
        """使用 Jinja2 Sandbox 严格渲染 Prompt；缺依赖时使用受限变量替换。"""
        prompt = self.get(prompt_id, version)
        try:
            if self._jinja is not None:
                rendered = self._jinja.from_string(prompt["content"]).render(**variables)
            else:
                rendered = self._strict_replace(prompt["content"], variables)
        except Exception as exc:
            raise GatewayError("Prompt 渲染失败", status_code=422, code="prompt_render_error", error_type="invalid_request_error") from exc
        return prompt, rendered

    @contextmanager
    def _connect(self):
        """创建事务连接，并确保在 Windows 等平台及时释放文件句柄。"""
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _strict_replace(source: str, variables: dict[str, Any]) -> str:
        """在缺少 Jinja2 时仅支持 {{ variable }} 的严格替换。"""
        def replace(match: re.Match[str]) -> str:
            key = match.group(1).strip()
            if key not in variables:
                raise KeyError(key)
            return str(variables[key])
        return re.sub(r"\{\{\s*([^}]+?)\s*\}\}", replace, source)


def apply_legacy_template(messages: list[Message], selection: TemplateReference) -> list[Message]:
    """保持 v3 规则：渲染后替换末条 user 消息或追加 user 消息。"""
    definition = LEGACY_TEMPLATES.get(selection.template_id)
    version = definition["default"] if definition and selection.version == "latest" else selection.version
    template = definition["versions"].get(version) if definition else None
    if template is None:
        raise GatewayError("模板不存在", status_code=404, code="unknown_template", error_type="invalid_request_error")
    try:
        rendered = PromptRepository._strict_replace(template, selection.variables)
    except KeyError as exc:
        raise GatewayError("缺少模板变量", status_code=422, code="missing_template_variable", error_type="invalid_request_error") from exc
    result = list(messages)
    if result and result[-1].role == "user":
        result[-1] = Message(role="user", content=rendered)
    else:
        result.append(Message(role="user", content=rendered))
    return result


def apply_static_prompt(messages: list[Message], selection: PromptSelection | None) -> list[Message]:
    """保持 v3 的受控静态系统 Prompt 注入能力。"""
    if selection is None:
        return messages
    source = STATIC_PROMPTS.get((selection.name, selection.version))
    if source is None:
        raise GatewayError("Prompt 模板不存在", status_code=404, code="unknown_prompt_template", error_type="invalid_request_error")
    try:
        content = re.sub(r"\$\{([^}]+)}", lambda match: selection.variables[match.group(1)], source)
    except KeyError as exc:
        raise GatewayError("缺少 Prompt 变量", status_code=422, code="missing_prompt_variable", error_type="invalid_request_error") from exc
    return [Message(role="system", content=content), *messages]


def get_legacy_template(template_id: str, version: str | None = None) -> dict[str, str] | None:
    """提供 v3 兼容模板查询响应。"""
    definition = LEGACY_TEMPLATES.get(template_id)
    if definition is None:
        return None
    actual_version = definition["default"] if version in (None, "latest") else version
    content = definition["versions"].get(actual_version)
    return {"template_id": template_id, "version": actual_version, "template": content} if content else None
