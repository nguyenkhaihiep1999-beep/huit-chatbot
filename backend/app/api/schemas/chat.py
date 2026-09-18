from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, ConfigDict, Field

class MessageItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"] = Field(description="Role của tin nhắn")
    content: str = Field(description="Nội dung tin nhắn")

class ChatRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "x-contract-id": "huit.api.chat-request",
            "x-contract-version": "1.0.0",
        },
    )

    question: str = Field(..., min_length=1, max_length=1000, description="Câu hỏi hoặc yêu cầu tư vấn")
    history: List[MessageItem] = Field(default_factory=list, description="Lịch sử hội thoại trước đó")
    enable_cache: bool = Field(default=True, description="Bật bộ nhớ đệm phản hồi")
    session_id: Optional[str] = Field(default=None, min_length=1, max_length=128, description="Mã phiên hội thoại")

class SourceCitation(BaseModel):
    i: int
    title: str
    url: str
    score: float
    text: str

class TraceStep(BaseModel):
    step: int
    name: str
    detail: str
    status: str

class ChatResponse(BaseModel):
    answer: str
    sources: List[SourceCitation] = []
    trace: List[TraceStep] = []
    visual: Optional[Dict[str, Any]] = None
    artifact: Optional[Dict[str, Any]] = None
    meta: Optional[Dict[str, Any]] = None
    request_id: Optional[str] = None
