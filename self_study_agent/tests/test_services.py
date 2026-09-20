"""模型驱动知识提炼与出题服务测试。"""

from __future__ import annotations

from typing import Any

import pytest

from study_agent.errors import StudyError
from study_agent.models import QuestionType
from study_agent.profile import StudyProfile
from study_agent.services import extract_concepts, generate_questions


class _RecordingModel:
    """记录系统提示词并按测试场景返回固定结构化结果。"""

    available = True

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        """保存等待返回的模型响应。"""
        self.prompts: list[str] = []
        self._responses = list(responses)

    def generate(self, system_prompt: str, payload: dict[str, Any], result_model: type[Any]) -> Any:
        """记录提示词，并通过调用方要求的 Pydantic 契约构造结果。"""
        self.prompts.append(system_prompt)
        return result_model.model_validate(self._responses.pop(0))


class _UnavailableModel:
    """模拟未配置的模型服务。"""

    available = False

    def generate(self, system_prompt: str, payload: dict[str, Any], result_model: type[Any]) -> Any:
        """未配置模型不应进入实际生成。"""
        raise AssertionError("不应调用未配置模型")


def test_profile_prompt_drives_agent_design_extraction() -> None:
    """验证 AI Agent 范围和完整句要求来自可编辑学习画像。"""
    profile = StudyProfile.load()
    model = _RecordingModel(
        [
            {
                "concepts": [
                    {
                        "title": "Tool Runtime 的执行边界",
                        "summary": "Tool Runtime 在执行前校验参数、权限和风险，避免候选调用直接产生副作用。",
                        "keywords": ["Tool Runtime", "权限控制"],
                        "chunk_index": 0,
                    }
                ]
            }
        ]
    )

    concepts, mode = extract_concepts(
        [{"chunk_index": 0, "text": "Tool Runtime 应在 Handler 前校验权限。"}], model, profile
    )

    assert mode == "model"
    assert concepts[0].title == "Tool Runtime 的执行边界"
    assert model.prompts == [profile.extraction_prompt]
    assert "Function Calling" in profile.extraction_prompt
    assert "不得截取原文半句" in profile.extraction_prompt


def test_model_is_required_and_question_source_links_are_validated() -> None:
    """验证不会回退离线规则，且模型题目必须关联给定知识点和来源。"""
    profile = StudyProfile.load()
    with pytest.raises(StudyError, match="配置") as error:
        extract_concepts([{"chunk_index": 0, "text": "Agent Loop"}], _UnavailableModel(), profile)
    assert error.value.code == "MODEL_UNAVAILABLE"

    concepts = [
        {
            "concept_id": "concept-1",
            "source_id": "source-1",
            "chunk_index": 0,
            "title": "Agent Loop 的工具调用闭环",
            "summary": "模型决策、工具执行和结果回写构成闭环。",
            "keywords": ["Agent Loop"],
        }
    ]
    model = _RecordingModel(
        [
            {
                "questions": [
                    {
                        "concept_id": "concept-1",
                        "question_type": QuestionType.SINGLE_CHOICE,
                        "prompt": "Agent Loop 中，工具结果返回模型的主要目的是什么？",
                        "options": ["让模型基于结果继续决策", "跳过权限校验", "删除审计记录", "关闭 Runtime"],
                        "answer": "让模型基于结果继续决策",
                        "explanation": "结果回写使模型能在下一轮基于真实观察继续决策。",
                    }
                ]
            }
        ]
    )

    questions, mode = generate_questions(concepts, model, profile)

    assert mode == "model"
    assert questions[0].source_refs == ["source-1#chunk-0"]
    assert model.prompts == [profile.question_prompt]
