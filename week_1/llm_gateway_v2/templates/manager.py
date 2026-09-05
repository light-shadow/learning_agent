# templates/manager.py
from typing import Dict, Optional, Any
import json

class TemplateManager:
    """内存存储的模板管理（支持版本）"""
    _templates = {
        "summarize": {
            "versions": {
                "v1": {"template": "请简要概括以下内容：\n{{text}}", "description": "基础概括"},
                "v2": {"template": "请用三句话概括以下文本：\n{{text}}", "description": "三句概括"},
            },
            "default_version": "v1"
        },
        "translate": {
            "versions": {
                "v1": {"template": "将以下内容翻译成{{target_lang}}：\n{{text}}", "description": "翻译"}
            },
            "default_version": "v1"
        }
    }

    @classmethod
    def get_template(cls, template_id: str, version: Optional[str] = None) -> Optional[Dict]:
        tpl = cls._templates.get(template_id)
        if not tpl:
            return None
        if version is None:
            version = tpl.get("default_version", "v1")
        return tpl["versions"].get(version)

    @classmethod
    def render(cls, template_str: str, variables: Dict[str, str]) -> str:
        """简单变量替换，支持 {{var}}"""
        import re
        def repl(match):
            key = match.group(1).strip()
            return variables.get(key, match.group(0))
        return re.sub(r'\{\{\s*([^}]+?)\s*\}\}', repl, template_str)

    @classmethod
    def apply_template(cls, request) -> list:
        """如果请求包含 template，则应用模板生成 messages"""
        if not request.template:
            return request.messages  # 原样返回

        tpl_data = cls.get_template(request.template.template_id, request.template.version)
        if not tpl_data:
            raise ValueError(f"Template {request.template.template_id} version {request.template.version} not found")

        template_str = tpl_data["template"]
        rendered = cls.render(template_str, request.template.variables)

        # 用渲染后的内容替换最后一条 user 消息的内容，或在系统消息中插入？
        # 简单：将渲染后作为系统或用户消息，这里假设替换最后一条用户消息
        messages = list(request.messages)
        if messages and messages[-1].role == "user":
            messages[-1].content = rendered
        else:
            # 否则追加一条用户消息
            from models import Message, Role
            messages.append(Message(role=Role.user, content=rendered))
        return messages