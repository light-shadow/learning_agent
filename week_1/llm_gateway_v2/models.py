# models.py
from pydantic import BaseModel, Field, validator
from typing import Optional, Dict, Any, List, Union
from enum import Enum

class Role(str, Enum):
    system = "system"
    user = "user"
    assistant = "assistant"

class Message(BaseModel):
    role: Role
    content: str

class TemplateReference(BaseModel):
    template_id: str
    version: Optional[str] = "latest"
    variables: Dict[str, str] = Field(default_factory=dict)

class ChatRequest(BaseModel):
    model: str                     # 统一模型名，如 deepseek-v4-pro
    messages: List[Message]
    stream: bool = False
    response_format: Optional[Dict[str, Any]] = None  # {"type": "json_object"} 或 {"type": "json_schema", "schema": {...}}
    template: Optional[TemplateReference] = None      # 若提供，则基于模板构建消息
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 4096

    @validator('model')
    def validate_model(cls, v):
        from config import MODEL_ROUTING
        if v not in MODEL_ROUTING:
            raise ValueError(f"Unsupported model: {v}")
        return v

class UsageInfo(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

class ChatResponse(BaseModel):
    id: str
    model: str                    # 实际模型名
    content: str
    usage: UsageInfo
    reasoning: Optional[str] = None   # 推理过程（如R1）
    latency_ms: float             # 总延迟毫秒
    first_token_latency_ms: Optional[float] = None