"""模型驱动的知识提炼、出题与评分服务。"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import Field

from .errors import StudyError
from .model_adapter import JsonModel
from .models import ConceptDraft, QuestionDraft, QuestionType, ShortAnswerGrade, StrictModel
from .profile import StudyProfile


LOGGER = logging.getLogger(__name__)


class ConceptResponse(StrictModel):
    """模型知识提炼结果的外层契约。"""

    concepts: list[ConceptDraft] = Field(min_length=1, max_length=20)


class GeneratedQuestionDraft(StrictModel):
    """模型生成的题目内容，不包含由 Runtime 管理的内部来源引用。"""

    concept_id: str = Field(min_length=1)
    question_type: QuestionType
    prompt: str = Field(min_length=1, max_length=1000)
    options: list[str] = Field(default_factory=list, max_length=6)
    answer: str = Field(min_length=1, max_length=800)
    explanation: str = Field(min_length=1, max_length=1000)


class QuestionResponse(StrictModel):
    """模型出题结果的外层契约。"""

    questions: list[GeneratedQuestionDraft] = Field(min_length=1, max_length=30)


def extract_concepts(
    chunks: list[dict[str, Any]], model: JsonModel, profile: StudyProfile
) -> tuple[list[ConceptDraft], str]:
    """调用模型依据学习画像提炼知识点，并验证其来源定位。"""
    _require_model(model)
    LOGGER.info("concept_extraction_started profile=%s chunk_count=%d", profile.name, len(chunks))
    response = model.generate(
        profile.extraction_prompt,
        {"profile": profile.name, "chunks": _model_chunks(chunks)},
        ConceptResponse,
    )
    valid = [item for item in response.concepts if item.chunk_index < len(chunks)]
    if not valid:
        raise StudyError("MODEL_CONTRACT_ERROR", "模型未返回关联有效文本块的知识点")
    LOGGER.info("concept_extraction_completed profile=%s concept_count=%d", profile.name, len(valid))
    return valid, "model"


def generate_questions(
    concepts: list[dict[str, Any]], model: JsonModel, profile: StudyProfile
) -> tuple[list[QuestionDraft], str]:
    """调用模型基于已保存知识点出题，并验证题目来源关系。"""
    _require_model(model)
    LOGGER.info("question_generation_started profile=%s concept_count=%d", profile.name, len(concepts))
    response = model.generate(
        profile.question_prompt,
        {"profile": profile.name, "concepts": concepts},
        QuestionResponse,
    )
    questions = _attach_source_refs(response.questions, concepts)
    LOGGER.info("question_generation_completed profile=%s question_count=%d", profile.name, len(questions))
    return questions, "model"


def grade_short_answer(
    question: dict[str, Any], answer: str, model: JsonModel, profile: StudyProfile
) -> ShortAnswerGrade:
    """调用模型按学习画像对简答题进行结构化评分。"""
    _require_model(model)
    LOGGER.info("short_answer_grading_started question_id=%s", question.get("question_id", "unknown"))
    grade = model.generate(
        profile.grading_prompt,
        {
            "profile": profile.name,
            "question": question["prompt"],
            "reference_answer": question["answer"],
            "explanation": question["explanation"],
            "student_answer": answer,
        },
        ShortAnswerGrade,
    )
    LOGGER.info(
        "short_answer_grading_completed question_id=%s score=%.2f",
        question.get("question_id", "unknown"),
        grade.score,
    )
    return grade


def _require_model(model: JsonModel) -> None:
    """要求模型服务已配置，禁止静默回退到规则式离线出题。"""
    if not model.available:
        raise StudyError("MODEL_UNAVAILABLE", "请配置 STUDY_AGENT_BASE_URL、API_KEY 和 MODEL 后再生成学习内容")


def _model_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按原始顺序向模型传递 PDF 文本块，不执行本地摘要或改写。"""
    return [{"chunk_index": item["chunk_index"], "text": item["text"]} for item in chunks]


def _attach_source_refs(
    questions: list[GeneratedQuestionDraft], concepts: list[dict[str, Any]]
) -> list[QuestionDraft]:
    """校验模型选择的知识点，并由 Runtime 写入不可伪造的来源引用。"""
    source_ref_by_concept = {
        str(concept["concept_id"]): f"{concept['source_id']}#chunk-{concept['chunk_index']}"
        for concept in concepts
    }
    enriched_questions: list[QuestionDraft] = []
    for question in questions:
        source_ref = source_ref_by_concept.get(question.concept_id)
        if source_ref is None:
            raise StudyError("MODEL_CONTRACT_ERROR", "模型题目引用了不存在的知识点")
        enriched_questions.append(QuestionDraft(**question.model_dump(), source_refs=[source_ref]))
    return enriched_questions
