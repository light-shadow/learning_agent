"""可配置的课程学习画像。"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import StudyError


DEFAULT_PROFILE_PATH = Path(__file__).resolve().parent.parent / "config" / "study_profile.toml"


@dataclass(frozen=True)
class StudyProfile:
    """定义某类课程的提炼、出题和评分提示词。"""

    name: str
    extraction_prompt: str
    question_prompt: str
    grading_prompt: str

    @classmethod
    def load(cls, path: Path | None = None) -> "StudyProfile":
        """从 TOML 文件加载学习画像，允许通过环境变量切换课程配置。"""
        profile_path = path or Path(os.getenv("STUDY_AGENT_PROFILE", DEFAULT_PROFILE_PATH))
        try:
            with profile_path.open("rb") as stream:
                raw = tomllib.load(stream)
        except OSError as exc:
            raise StudyError("STUDY_PROFILE_NOT_FOUND", f"学习画像配置不可读取：{profile_path}") from exc
        return cls(
            name=_required_text(raw, "profile", "name"),
            extraction_prompt=_required_text(raw, "extraction", "system_prompt"),
            question_prompt=_required_text(raw, "quiz", "system_prompt"),
            grading_prompt=_required_text(raw, "grading", "system_prompt"),
        )


def _required_text(raw: dict[str, Any], section: str, key: str) -> str:
    """读取非空配置文本，防止不完整画像静默降低内容质量。"""
    value = raw.get(section, {}).get(key) if isinstance(raw.get(section), dict) else None
    if not isinstance(value, str) or not value.strip():
        raise StudyError("STUDY_PROFILE_INVALID", f"学习画像缺少 {section}.{key}")
    return value.strip()
