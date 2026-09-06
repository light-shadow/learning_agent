"""受控 Prompt 与兼容 v2 模板管理。"""
from __future__ import annotations

import re
from string import Template

from errors import GatewayError
from models import Message, PromptSelection, TemplateReference


LEGACY_TEMPLATES = {
    "summarize": {
        "default_version": "v1",
        "versions": {
            "v1": "请简要概括以下内容：\n{{text}}",
            "v2": "请用三句话概括以下文本：\n{{text}}",
        },
    },
    "translate": {
        "default_version": "v1",
        "versions": {"v1": "将以下内容翻译成{{target_lang}}：\n{{text}}"},
    },
}

PROMPT_TEMPLATES = {
    ("knowledge_decision", "v1"): "你是${product_name}的知识库决策器。资料不足时搜索，资料充分时结束回答。不得编造制度内容。",
}


def get_legacy_template(template_id: str, version: str | None = None) -> dict[str, str] | None:
    """按模板标识和版本获取兼容 v2 的模板描述。"""
    template = LEGACY_TEMPLATES.get(template_id)
    if template is None:
        return None
    actual_version = template["default_version"] if version in (None, "latest") else version
    content = template["versions"].get(actual_version)
    if content is None:
        return None
    return {"template_id": template_id, "version": actual_version, "template": content}


def apply_legacy_template(messages: list[Message], selection: TemplateReference) -> list[Message]:
    """按 v2 规则渲染模板并替换最后一条用户消息或追加用户消息。"""
    definition = get_legacy_template(selection.template_id, selection.version)
    if definition is None:
        raise GatewayError("unknown_template", "模板不存在", 400)

    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        if key not in selection.variables:
            missing.append(key)
            return match.group(0)
        return selection.variables[key]

    rendered = re.sub(r"\{\{\s*([^}]+?)\s*\}\}", replace, definition["template"])
    if missing:
        raise GatewayError("missing_template_variable", f"缺少模板变量: {missing[0]}", 400)

    result = list(messages)
    if result and result[-1].role == "user":
        result[-1] = Message(role="user", content=rendered)
    else:
        result.append(Message(role="user", content=rendered))
    return result


def render_prompt(selection: PromptSelection) -> Message:
    """渲染受控系统 Prompt，并在变量缺失时返回稳定错误码。"""
    source = PROMPT_TEMPLATES.get((selection.name, selection.version))
    if source is None:
        raise GatewayError("unknown_prompt_template", "Prompt 模板不存在", 400)
    try:
        content = Template(source).substitute(selection.variables)
    except KeyError as exc:
        raise GatewayError("missing_prompt_variable", f"缺少 Prompt 变量: {exc.args[0]}", 400) from exc
    return Message(role="system", content=content)
