"""统一 Runtime、SQLite 持久化和学习闭环测试。"""

from __future__ import annotations

from pathlib import Path

from docx import Document

from study_agent.models import ToolCall
from study_agent.runtime import ExecutionContext, StudyRuntime
from study_agent.storage import StudyStore


def _create_docx(tmp_path: Path) -> Path:
    """创建用于离线学习流程的最小 DOCX 资料。"""
    path = tmp_path / "agent.docx"
    document = Document()
    document.add_paragraph("Agent Loop 会把 Tool Result 写回上下文，再由模型决定下一步。")
    document.add_paragraph("Tool Runtime 必须在 Handler 执行前校验输入、权限和风险。")
    document.save(path)
    return path


def _call(name: str, arguments: dict[str, object]) -> ToolCall:
    """构造稳定的测试工具调用。"""
    return ToolCall(tool_call_id=f"call_{name}", name=name, arguments=arguments)


def test_offline_learning_flow_persists_and_prioritizes_weak_concepts(tmp_path: Path) -> None:
    """验证导入、提炼、出题、作答、掌握度和重启恢复的完整闭环。"""
    database = tmp_path / "study.sqlite3"
    store = StudyStore(database)
    runtime = StudyRuntime(store)

    imported = runtime.invoke(_call("ingest_docx", {"path": str(_create_docx(tmp_path))}))
    assert imported.ok is True
    source_id = imported.content["source_id"]
    concepts = runtime.invoke(_call("extract_concepts", {"source_id": source_id}))
    assert concepts.ok is True
    quiz = runtime.invoke(_call("generate_quiz", {"source_id": source_id}))
    assert quiz.ok is True

    questions = store.select_questions("default", source_id, 10)
    single_choice = next(item for item in questions if item["question_type"] == "single_choice")
    outcome = runtime.grade("default", single_choice["question_id"], single_choice["answer"])
    assert outcome.status == "correct"
    assert outcome.mastery is not None and outcome.mastery > 0.5

    wrong = runtime.grade("default", single_choice["question_id"], "错误答案")
    assert wrong.status == "incorrect"
    assert wrong.mastery is not None and wrong.mastery < outcome.mastery
    assert store.review("default")[0]["mastery"] <= store.review("default")[-1]["mastery"]
    store.close()

    reopened = StudyStore(database)
    assert len(reopened.list_sources()) == 1
    assert reopened.review("default")
    reopened.close()


def test_runtime_blocks_disallowed_and_invalid_calls_before_handler(tmp_path: Path) -> None:
    """验证白名单与参数校验拒绝不会触发真实 Handler。"""
    store = StudyStore(tmp_path / "study.sqlite3")
    runtime = StudyRuntime(store)

    denied = runtime.invoke(_call("ingest_docx", {"path": "ignored.docx"}), ExecutionContext(frozenset()))
    assert denied.code == "TOOL_NOT_ALLOWED"
    assert runtime.get_handler_call_count("ingest_docx") == 0

    invalid = runtime.invoke(_call("ingest_docx", {"unknown": "ignored.docx"}))
    assert invalid.code == "INVALID_ARGUMENT"
    assert runtime.get_handler_call_count("ingest_docx") == 0
    assert store.list_audit()[-1]["code"] == "INVALID_ARGUMENT"
    store.close()


def test_short_answer_is_manual_review_without_model(tmp_path: Path) -> None:
    """验证离线模式不伪造简答评分，也不会改变掌握度。"""
    store = StudyStore(tmp_path / "study.sqlite3")
    runtime = StudyRuntime(store)
    imported = runtime.invoke(_call("ingest_docx", {"path": str(_create_docx(tmp_path))}))
    source_id = imported.content["source_id"]
    runtime.invoke(_call("extract_concepts", {"source_id": source_id}))
    runtime.invoke(_call("generate_quiz", {"source_id": source_id}))
    question = next(item for item in store.select_questions("default", source_id, 20) if item["question_type"] == "short_answer")

    result = runtime.grade("default", question["question_id"], "这是我的理解")

    assert result.status == "manual_review"
    assert result.score is None
    assert result.mastery is None
    store.close()
