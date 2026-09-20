"""统一 Runtime、模型服务与学习闭环测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from study_agent.models import QuestionType, ToolCall
from study_agent.runtime import ExecutionContext, StudyRuntime
from study_agent.storage import StudyStore


class _LearningModel:
    """为学习闭环测试动态生成符合来源关系的结构化响应。"""

    available = True

    def generate(self, system_prompt: str, payload: dict[str, Any], result_model: type[Any]) -> Any:
        """根据请求的结果契约返回知识点、题目或简答评分。"""
        if result_model.__name__ == "ConceptResponse":
            response = {
                "concepts": [
                    {
                        "title": "Agent Loop 的工具调用闭环",
                        "summary": "Agent Loop 将模型决策、工具执行和 Tool Result 回写连接为连续闭环。",
                        "keywords": ["Agent Loop", "Tool Result"],
                        "chunk_index": 0,
                    }
                ]
            }
        elif result_model.__name__ == "QuestionResponse":
            concept = payload["concepts"][0]
            response = {
                "questions": [
                    {
                        "concept_id": concept["concept_id"],
                        "question_type": QuestionType.SINGLE_CHOICE,
                        "prompt": "Agent Loop 中，Tool Result 回写模型的主要作用是什么？",
                        "options": ["支持模型基于结果继续决策", "跳过权限校验", "删除审计记录", "关闭 Runtime"],
                        "answer": "支持模型基于结果继续决策",
                        "explanation": "结果回写使模型能基于真实观察继续决策。",
                    },
                    {
                        "concept_id": concept["concept_id"],
                        "question_type": QuestionType.SHORT_ANSWER,
                        "prompt": "说明 Tool Result 回写在 Agent Loop 中的作用。",
                        "options": [],
                        "answer": "将工具执行结果带回模型，使模型可以依据真实观察继续决策。",
                        "explanation": "应说明结果回写和下一轮决策的关系。",
                    },
                ]
            }
        else:
            response = {
                "score": 0.8,
                "feedback": "已说明结果回写支持下一轮模型决策。",
                "matched_points": ["结果回写", "下一轮决策"],
                "missing_points": [],
            }
        return result_model.model_validate(response)


def _create_pdf(tmp_path: Path) -> Path:
    """创建用于模型驱动学习流程的最小 AI Agent 课程 PDF。"""
    path = tmp_path / "agent.pdf"
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    stream.set_data(
        b"BT /F1 12 Tf 72 720 Td (Agent Loop writes Tool Result back to the model.) Tj "
        b"0 -24 Td (Tool Runtime validates input and permissions before handlers.) Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    with path.open("wb") as output:
        writer.write(output)
    return path


def _call(name: str, arguments: dict[str, object]) -> ToolCall:
    """构造稳定的测试工具调用。"""
    return ToolCall(tool_call_id=f"call_{name}", name=name, arguments=arguments)


def test_model_learning_flow_persists_and_prioritizes_weak_concepts(tmp_path: Path) -> None:
    """验证 PDF 导入、模型提炼、模型出题、评分和重启恢复的完整闭环。"""
    database = tmp_path / "study.sqlite3"
    store = StudyStore(database)
    runtime = StudyRuntime(store, model=_LearningModel())

    imported = runtime.invoke(_call("ingest_pdf", {"path": str(_create_pdf(tmp_path))}))
    assert imported.ok is True
    source_id = imported.content["source_id"]
    concepts = runtime.invoke(_call("extract_concepts", {"source_id": source_id}))
    assert concepts.ok is True and concepts.content["mode"] == "model"
    quiz = runtime.invoke(_call("generate_quiz", {"source_id": source_id}))
    assert quiz.ok is True and quiz.content["mode"] == "model"

    questions = store.select_questions("default", source_id, 10)
    single_choice = next(item for item in questions if item["question_type"] == "single_choice")
    outcome = runtime.grade("default", single_choice["question_id"], single_choice["answer"])
    assert outcome.status == "correct"
    assert outcome.mastery is not None and outcome.mastery > 0.5

    wrong = runtime.grade("default", single_choice["question_id"], "错误答案")
    assert wrong.status == "incorrect"
    assert wrong.mastery is not None and wrong.mastery < outcome.mastery
    assert store.review("default")[0]["mastery"] <= store.review("default")[-1]["mastery"]
    history = store.list_attempt_history("default", source_id)
    assert len(history) == 2
    assert history[0]["prompt"] == single_choice["prompt"]
    assert history[0]["status"] == "incorrect"
    assert history[0]["concept_title"] == "Agent Loop 的工具调用闭环"
    store.close()

    reopened = StudyStore(database)
    assert len(reopened.list_sources()) == 1
    assert reopened.review("default")
    assert len(reopened.list_attempt_history("default", source_id)) == 2
    reopened.close()


def test_runtime_only_registers_pdf_ingestion_and_blocks_invalid_calls(tmp_path: Path) -> None:
    """验证 Runtime 不暴露 DOCX、网页工具，并在 Handler 前拒绝非法 PDF 调用。"""
    store = StudyStore(tmp_path / "study.sqlite3")
    runtime = StudyRuntime(store, model=_LearningModel())

    assert runtime._registry.names == {
        "ingest_pdf",
        "extract_concepts",
        "generate_quiz",
        "grade_answer",
    }
    denied = runtime.invoke(_call("ingest_pdf", {"path": "ignored.pdf"}), ExecutionContext(frozenset()))
    assert denied.code == "TOOL_NOT_ALLOWED"
    assert runtime.get_handler_call_count("ingest_pdf") == 0

    invalid = runtime.invoke(_call("ingest_pdf", {"unknown": "ignored.pdf"}))
    assert invalid.code == "INVALID_ARGUMENT"
    assert runtime.get_handler_call_count("ingest_pdf") == 0
    assert store.list_audit()[-1]["code"] == "INVALID_ARGUMENT"

    removed = runtime.invoke(_call("ingest_docx", {"path": "ignored.docx"}))
    assert removed.code == "TOOL_NOT_ALLOWED"
    assert runtime.get_handler_call_count("ingest_docx") == 0
    store.close()


def test_short_answer_uses_model_scoring(tmp_path: Path) -> None:
    """验证简答题必须调用模型并以结构化评分更新掌握度。"""
    store = StudyStore(tmp_path / "study.sqlite3")
    runtime = StudyRuntime(store, model=_LearningModel())
    imported = runtime.invoke(_call("ingest_pdf", {"path": str(_create_pdf(tmp_path))}))
    source_id = imported.content["source_id"]
    runtime.invoke(_call("extract_concepts", {"source_id": source_id}))
    runtime.invoke(_call("generate_quiz", {"source_id": source_id}))
    question = next(
        item
        for item in store.select_questions("default", source_id, 20)
        if item["question_type"] == "short_answer"
    )

    result = runtime.grade("default", question["question_id"], "工具结果要返回给模型继续决策")

    assert result.status == "correct"
    assert result.score == 0.8
    assert result.mastery is not None
    store.close()
