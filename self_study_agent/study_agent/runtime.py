"""唯一的资料处理与学习闭环 Runtime。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable
from uuid import uuid4

from pydantic import Field, ValidationError

from .errors import StudyError
from .model_adapter import JsonModel, OpenAICompatibleModel
from .models import AttemptOutcome, QuestionType, StrictModel, ToolCall, ToolResult
from .readers import fetch_web_source, read_local_source
from .services import extract_concepts, generate_questions, grade_short_answer
from .storage import StudyStore


class IngestInput(StrictModel):
    """本地资料导入参数。"""

    path: str = Field(min_length=1, max_length=1000)


class WebInput(StrictModel):
    """网页导入参数。"""

    url: str = Field(min_length=1, max_length=2000)


class SourceInput(StrictModel):
    """知识提炼和出题的资料参数。"""

    source_id: str = Field(min_length=1, max_length=100)


class GradeInput(StrictModel):
    """作答评分参数。"""

    learner_id: str = Field(min_length=1, max_length=80)
    question_id: str = Field(min_length=1, max_length=100)
    answer: str = Field(min_length=1, max_length=3000)


@dataclass(frozen=True)
class ExecutionContext:
    """Runtime 的可信执行上下文。"""

    allowed_tools: frozenset[str]
    mode: str = "default"


@dataclass(frozen=True)
class ToolDefinition:
    """完整工具定义，模型可见内容与执行实现保持分离。"""

    name: str
    input_model: type[StrictModel]
    handler: Callable[[StrictModel], dict[str, Any]]


class ToolRegistry:
    """保存注册工具并创建运行级冻结快照。"""

    def __init__(self) -> None:
        """初始化空工具目录。"""
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        """注册唯一工具名，防止运行时覆盖。"""
        if definition.name in self._tools:
            raise ValueError(f"重复工具注册：{definition.name}")
        self._tools[definition.name] = definition

    def snapshot(self, allowed_tools: frozenset[str]) -> dict[str, ToolDefinition]:
        """冻结本次运行可执行的工具集合。"""
        return {name: tool for name, tool in self._tools.items() if name in allowed_tools}

    @property
    def names(self) -> frozenset[str]:
        """返回所有已注册工具名。"""
        return frozenset(self._tools)


class StudyRuntime:
    """所有资料读取、知识处理和作答评分的唯一执行入口。"""

    def __init__(self, store: StudyStore, model: JsonModel | None = None) -> None:
        """装配存储、可选模型和工具注册表。"""
        self._store = store
        self._model = model or OpenAICompatibleModel()
        self._registry = ToolRegistry()
        self._handler_calls: dict[str, int] = {}
        self._register_tools()

    def invoke(self, call: ToolCall, context: ExecutionContext | None = None) -> ToolResult:
        """按 prepare、execute、finalize 三阶段处理一次候选工具动作。"""
        context = context or ExecutionContext(allowed_tools=self._registry.names)
        snapshot = self._registry.snapshot(context.allowed_tools)
        started_at = time.perf_counter()
        source_refs: list[str] = []
        try:
            tool = snapshot.get(call.name)
            if tool is None:
                raise StudyError("TOOL_NOT_ALLOWED", "工具不在本次运行白名单中")
            arguments = tool.input_model.model_validate(call.arguments)
            self._handler_calls[call.name] = self._handler_calls.get(call.name, 0) + 1
            content = tool.handler(arguments)
            source_refs = list(content.pop("source_refs", []))
            result = ToolResult(
                tool_call_id=call.tool_call_id,
                tool_name=call.name,
                ok=True,
                code="OK",
                content=_limit_content(content),
                source_refs=source_refs,
            )
        except ValidationError as exc:
            result = ToolResult(
                tool_call_id=call.tool_call_id,
                tool_name=call.name,
                ok=False,
                code="INVALID_ARGUMENT",
                content={"message": "工具参数不合法", "fields": [item["loc"] for item in exc.errors()]},
            )
        except StudyError as exc:
            result = ToolResult(
                tool_call_id=call.tool_call_id,
                tool_name=call.name,
                ok=False,
                code=exc.code,
                content={"message": exc.message},
                source_refs=source_refs,
            )
        except Exception:
            result = ToolResult(
                tool_call_id=call.tool_call_id,
                tool_name=call.name,
                ok=False,
                code="TOOL_EXECUTION_FAILED",
                content={"message": "工具执行失败，请查看本地审计记录。"},
                source_refs=source_refs,
            )
        self._store.add_audit(
            call.tool_call_id,
            call.name,
            result.code,
            list(call.arguments),
            result.source_refs,
        )
        return result

    def grade(self, learner_id: str, question_id: str, answer: str) -> AttemptOutcome:
        """通过 grade_answer 工具检查作答，并返回掌握度反馈。"""
        result = self.invoke(
            ToolCall(
                tool_call_id=f"call_{uuid4().hex}",
                name="grade_answer",
                arguments={"learner_id": learner_id, "question_id": question_id, "answer": answer},
            )
        )
        if not result.ok:
            raise StudyError(result.code, str(result.content["message"]))
        # SQLite 持久化后的枚举值会还原为字符串；在严格契约校验前显式恢复枚举。
        outcome = dict(result.content)
        outcome["question_type"] = QuestionType(outcome["question_type"])
        return AttemptOutcome.model_validate(outcome)

    def get_handler_call_count(self, tool_name: str) -> int:
        """返回真实 Handler 调用次数，供安全边界测试断言。"""
        return self._handler_calls.get(tool_name, 0)

    def _register_tools(self) -> None:
        """注册首版全部资料和学习闭环工具。"""
        self._registry.register(ToolDefinition("ingest_pdf", IngestInput, self._ingest_local))
        self._registry.register(ToolDefinition("ingest_docx", IngestInput, self._ingest_local))
        self._registry.register(ToolDefinition("fetch_webpage", WebInput, self._ingest_web))
        self._registry.register(ToolDefinition("extract_concepts", SourceInput, self._extract_concepts))
        self._registry.register(ToolDefinition("generate_quiz", SourceInput, self._generate_quiz))
        self._registry.register(ToolDefinition("grade_answer", GradeInput, self._grade_answer))

    def _ingest_local(self, arguments: StrictModel) -> dict[str, Any]:
        """读取 PDF 或 DOCX 并持久化受控文本块。"""
        source = read_local_source(arguments.path)  # type: ignore[attr-defined]
        source_id, created = self._store.add_source(source)
        return {
            "source_id": source_id,
            "created": created,
            "source_type": source.source_type.value,
            "title": source.title,
            "chunk_count": len(source.chunks),
            "source_refs": [source_id],
        }

    def _ingest_web(self, arguments: StrictModel) -> dict[str, Any]:
        """抓取静态网页并持久化受控正文。"""
        source = fetch_web_source(arguments.url)  # type: ignore[attr-defined]
        source_id, created = self._store.add_source(source)
        return {
            "source_id": source_id,
            "created": created,
            "source_type": source.source_type.value,
            "title": source.title,
            "chunk_count": len(source.chunks),
            "source_refs": [source_id],
        }

    def _extract_concepts(self, arguments: StrictModel) -> dict[str, Any]:
        """按来源文本块生成知识点并保存来源关系。"""
        source_id = arguments.source_id  # type: ignore[attr-defined]
        if not self._store.get_source(source_id):
            raise StudyError("SOURCE_NOT_FOUND", "资料不存在")
        concepts, mode = extract_concepts(self._store.get_chunks(source_id), self._model)
        concept_ids = self._store.replace_concepts(source_id, concepts)
        return {"source_id": source_id, "concept_ids": concept_ids, "mode": mode, "source_refs": [source_id]}

    def _generate_quiz(self, arguments: StrictModel) -> dict[str, Any]:
        """为资料知识点生成并保存混合题型。"""
        source_id = arguments.source_id  # type: ignore[attr-defined]
        concepts = self._store.list_concepts(source_id)
        if not concepts:
            raise StudyError("CONCEPTS_NOT_READY", "请先执行 extract_concepts")
        questions, mode = generate_questions(concepts, self._model)
        question_ids = self._store.add_questions(questions)
        return {"source_id": source_id, "question_ids": question_ids, "mode": mode, "source_refs": [source_id]}

    def _grade_answer(self, arguments: StrictModel) -> dict[str, Any]:
        """评分单选、判断和简答，并按结果更新掌握度。"""
        question = self._store.get_question(arguments.question_id)  # type: ignore[attr-defined]
        if question is None:
            raise StudyError("QUESTION_NOT_FOUND", "题目不存在")
        answer = arguments.answer.strip()  # type: ignore[attr-defined]
        question_type = QuestionType(question["question_type"])
        if question_type is QuestionType.SHORT_ANSWER:
            grade = grade_short_answer(question, answer, self._model)
            if grade is None:
                score = None
                status = "manual_review"
                feedback = f"离线模式无法可靠评分简答。参考要点：{question['explanation']}"
            else:
                score = grade.score
                status = "correct" if score >= 0.6 else "incorrect"
                feedback = grade.feedback
        else:
            score = 1.0 if _normalize(answer) == _normalize(question["answer"]) else 0.0
            status = "correct" if score == 1.0 else "incorrect"
            feedback = question["explanation"] if score else f"答案不正确。{question['explanation']}"
        mastery = self._store.save_attempt(arguments.learner_id, question, answer, score, status, feedback)  # type: ignore[attr-defined]
        return AttemptOutcome(
            question_id=question["question_id"],
            question_type=question_type,
            status=status,
            score=score,
            feedback=feedback,
            mastery=mastery,
        ).model_dump(mode="json")


def _normalize(value: str) -> str:
    """规范化可自动评分答案的大小写与空白。"""
    return "".join(value.lower().split())


def _limit_content(content: dict[str, Any], max_chars: int = 8000) -> dict[str, Any]:
    """限制工具结果大小，避免资料正文直接挤占后续上下文。"""
    rendered = str(content)
    if len(rendered) <= max_chars:
        return content
    return {"summary": rendered[:max_chars], "truncated": True}
