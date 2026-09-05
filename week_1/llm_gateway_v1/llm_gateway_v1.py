#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
统一 LLM 调用服务 - DeepSeek 完整实现
支持同步和流式调用，兼容 DeepSeek-V3 和 DeepSeek-R1。
"""

import os
from typing import List, Dict, Any, Optional, Generator
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

# 依赖安装: pip install openai
from openai import OpenAI


# ======================== 统一数据结构 ========================
@dataclass
class ChatResponse:
    """统一响应格式"""
    content: str                         # 最终回答内容
    model: str                           # 实际使用的模型
    usage: Dict[str, Any] = field(default_factory=dict)  # token 用量及其他元数据
    reasoning: Optional[str] = None      # 推理过程（仅 R1 模型有）


# ======================== 抽象基类 ========================
class BaseProvider(ABC):
    """所有 LLM 提供者的抽象基类"""

    @abstractmethod
    def chat(self, messages: List[Dict[str, str]], **kwargs) -> ChatResponse:
        """非流式调用，返回完整响应"""
        pass

    @abstractmethod
    def chat_stream(self, messages: List[Dict[str, str]], **kwargs) -> Generator[str, None, None]:
        """流式调用，yield 每个文本片段（不含推理部分）"""
        pass


# ======================== DeepSeek 实现 ========================
class DeepSeekProvider(BaseProvider):
    """
    DeepSeek 提供者，兼容 OpenAI SDK。
    模型: deepseek-chat (V3) 或 deepseek-reasoner (R1)
    """

    DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
    DEFAULT_MODEL = "deepseek-chat"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = DEFAULT_MODEL,
    ):
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise ValueError("DeepSeek API Key 必须通过参数或环境变量 DEEPSEEK_API_KEY 提供")

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=base_url or self.DEFAULT_BASE_URL,
        )
        self.model = model

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> ChatResponse:
        """
        同步非流式调用。
        支持额外参数: temperature, max_tokens, top_p, frequency_penalty, presence_penalty,
        response_format (json_object), tools 等，直接透传给 OpenAI SDK。
        """
        try:
            response = self.client.chat.completions.create(
                model=kwargs.get("model", self.model),
                messages=messages,
                stream=False,
                temperature=kwargs.get("temperature", 0.7),
                max_tokens=kwargs.get("max_tokens", 4096),
                top_p=kwargs.get("top_p", 1.0),
                frequency_penalty=kwargs.get("frequency_penalty", 0.0),
                presence_penalty=kwargs.get("presence_penalty", 0.0),
                # 如果指定了 response_format，会要求模型输出 JSON
                response_format=kwargs.get("response_format"),
                # 工具调用支持
                tools=kwargs.get("tools"),
                tool_choice=kwargs.get("tool_choice"),
            )

            choice = response.choices[0]
            message = choice.message
            content = message.content or ""
            reasoning = getattr(message, "reasoning_content", None)

            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

            return ChatResponse(
                content=content,
                model=response.model,
                usage=usage,
                reasoning=reasoning,
            )
        except Exception as e:
            raise RuntimeError(f"DeepSeek API 调用失败: {e}") from e

    def chat_stream(self, messages: List[Dict[str, str]], **kwargs) -> Generator[str, None, None]:
        """
        流式调用，yield 文本片段（不包含推理部分）。
        如果需要同时获取推理，可以扩展此方法返回复合对象。
        """
        try:
            stream = self.client.chat.completions.create(
                model=kwargs.get("model", self.model),
                messages=messages,
                stream=True,
                temperature=kwargs.get("temperature", 0.7),
                max_tokens=kwargs.get("max_tokens", 4096),
                top_p=kwargs.get("top_p", 1.0),
                frequency_penalty=kwargs.get("frequency_penalty", 0.0),
                presence_penalty=kwargs.get("presence_penalty", 0.0),
                # 流式下 response_format 可能不支持所有模型，谨慎使用
                # response_format=kwargs.get("response_format"),
            )

            for chunk in stream:
                if chunk.choices:
                    delta = chunk.choices[0].delta
                    # 只输出最终回答内容，忽略推理（若需推理可单独处理）
                    if delta.content:
                        yield delta.content
        except Exception as e:
            raise RuntimeError(f"DeepSeek 流式调用失败: {e}") from e


# ======================== 统一客户端 ========================
class UnifiedLLMClient:
    """统一客户端，工厂模式创建 Provider"""

    # 注册所有可用 Provider
    _providers = {
        "deepseek": DeepSeekProvider,
        # 可继续添加 OpenAI, Anthropic 等
    }

    def __init__(self, provider: str, **provider_kwargs):
        """
        :param provider: 提供者名称，如 'deepseek'
        :param provider_kwargs: 传递给 Provider 构造函数的参数（如 api_key, model）
        """
        provider_class = self._providers.get(provider.lower())
        if not provider_class:
            raise ValueError(f"不支持的提供者: {provider}，可用: {list(self._providers.keys())}")

        self.provider = provider_class(**provider_kwargs)

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> ChatResponse:
        """非流式调用"""
        return self.provider.chat(messages, **kwargs)

    def chat_stream(self, messages: List[Dict[str, str]], **kwargs) -> Generator[str, None, None]:
        """流式调用"""
        yield from self.provider.chat_stream(messages, **kwargs)


# ======================== 使用示例 ========================
if __name__ == "__main__":
    # 确保环境变量 DEEPSEEK_API_KEY 已设置，或在代码中直接传入
    # os.environ["DEEPSEEK_API_KEY"] = "sk-xxx"

    # ---------- 创建客户端（使用 DeepSeek-V3） ----------
    client = UnifiedLLMClient("deepseek", model="deepseek-chat")

    # 准备消息
    messages = [
        {"role": "system", "content": "你是一个有用的助手。"},
        {"role": "user", "content": "用一句话解释什么是 RAG（检索增强生成）？"}
    ]

    # 1. 非流式调用（Chat Completion）
    print("===== 非流式响应 =====")
    resp = client.chat(messages, temperature=0.5)
    print(f"模型: {resp.model}")
    print(f"回答: {resp.content}")
    print(f"Token 用量: {resp.usage}")
    if resp.reasoning:
        print(f"推理过程: {resp.reasoning}")

    # 2. 流式调用（Output）
    print("\n===== 流式响应 =====")
    print("回答: ", end="", flush=True)
    for chunk in client.chat_stream(messages, temperature=0.5):
        print(chunk, end="", flush=True)
    print("\n")

    # ---------- 使用 DeepSeek-R1（带推理） ----------
    print("===== DeepSeek-R1 示例 =====")
    client_r1 = UnifiedLLMClient("deepseek", model="deepseek-reasoner")

    r1_messages = [{"role": "user", "content": "1+1 等于几？请给出详细推理步骤。"}]

    # 非流式获取推理内容
    resp_r1 = client_r1.chat(r1_messages)
    print(f"模型: {resp_r1.model}")
    print(f"推理过程:\n{resp_r1.reasoning}")
    print(f"最终回答: {resp_r1.content}")

    # 流式输出（只输出最终回答，不输出推理）
    print("\n流式输出最终回答: ", end="", flush=True)
    for chunk in client_r1.chat_stream(r1_messages):
        print(chunk, end="", flush=True)
    print("\n")