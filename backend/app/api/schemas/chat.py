from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class MessageItem(BaseModel):
    role: str = Field(description="Role của tin nhắn (user hoặc assistant)")
    content: str = Field(description="Nội dung tin nhắn")

class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000, description="Câu hỏi hoặc yêu cầu tư vấn")
    history: Optional[List[MessageItem]] = Field(default=[], description="Lịch sử hội thoại trước đó")
    enable_cache: bool = Field(default=True, description="Bật bộ nhớ đệm phản hồi")
    session_id: Optional[str] = Field(default=None, description="Mã phiên hội thoại")

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
