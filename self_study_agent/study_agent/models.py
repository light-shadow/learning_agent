"""自学 Agent 的稳定数据契约。"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """拒绝模型或 CLI 传入的未声明字段。"""

    model_config = ConfigDict(extra="forbid", strict=True)


class SourceType(str, Enum):
    """首版允许的资料来源类型。"""

    PDF = "pdf"
    DOCX = "docx"
    WEB = "web"


class QuestionType(str, Enum):
    """首版支持的题型。"""

    SINGLE_CHOICE = "single_choice"
    TRUE_FALSE = "true_false"
    SHORT_ANSWER = "short_answer"


class ToolCall(StrictModel):
    """Runtime 执行的一次候选动作。"""

    tool_call_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=80)
    arguments: dict[str, Any]


class ToolResult(StrictModel):
    """统一工具结果，供 CLI 或后续 Agent Loop 消费。"""

    tool_call_id: str
    tool_name: str
    ok: bool
    code: str
    content: dict[str, Any]
    source_refs: list[str] = Field(default_factory=list)


class SourceChunk(StrictModel):
    """具备来源定位的清洗文本块。"""

    chunk_index: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=8000)


class ConceptDraft(StrictModel):
    """模型或离线规则生成的知识点。"""

    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=800)
    keywords: list[str] = Field(min_length=1, max_length=8)
    chunk_index: int = Field(ge=0)


class QuestionDraft(StrictModel):
    """写入题库前的题目契约。"""

    concept_id: str = Field(min_length=1)
    question_type: QuestionType
    prompt: str = Field(min_length=1, max_length=1000)
    options: list[str] = Field(default_factory=list, max_length=6)
    answer: str = Field(min_length=1, max_length=800)
    explanation: str = Field(min_length=1, max_length=1000)
    source_refs: list[str] = Field(min_length=1, max_length=5)


class ShortAnswerGrade(StrictModel):
    """模型评分器的结构化输出。"""

    score: float = Field(ge=0, le=1)
    feedback: str = Field(min_length=1, max_length=1000)
    matched_points: list[str] = Field(default_factory=list, max_length=8)
    missing_points: list[str] = Field(default_factory=list, max_length=8)


class AttemptOutcome(StrictModel):
    """一次作答后的统一反馈。"""

    question_id: str
    question_type: QuestionType
    status: Literal["correct", "incorrect", "manual_review"]
    score: float | None
    feedback: str
    mastery: float | None
