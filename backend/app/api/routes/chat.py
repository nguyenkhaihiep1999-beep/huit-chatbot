import logging
import re
from typing import Optional
from fastapi import APIRouter, Request, Header, Depends, HTTPException
from fastapi.responses import StreamingResponse
from backend.app.api.schemas.chat import ChatRequest, ChatResponse
from backend.app.api.dependencies.auth import get_current_principal, Principal
from backend.app.rag.pipeline import answer
from backend.app.telemetry.logger import set_current_request_id
from backend.app.services.stream_coordinator import get_stream_coordinator

logger = logging.getLogger("huit_chatbot.chat_route")
router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def handle_chat(
    req: ChatRequest,
    request: Request,
    x_request_id: Optional[str] = Header(None),
    principal: Principal = Depends(get_current_principal)
):
    """Endpoint xử lý câu hỏi tư vấn tuyển sinh đồng bộ (synchronous)."""
    req_id = set_current_request_id(x_request_id or getattr(request.state, "request_id", None))
    history_dicts = [h.model_dump() for h in req.history] if req.history else []
    res = answer(
        question=req.question,
        chat_history=history_dicts,
        use_cache=req.enable_cache,
        request_id=req_id,
        owner_id=principal.user_id
    )
    return res


@router.post("/chat/{request_id}/cancel")
async def cancel_chat_request(
    request_id: str,
    principal: Principal = Depends(get_current_principal),
):
    """Hủy phiên stream đang hoạt động theo request_id."""
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{8,128}", request_id):
        raise HTTPException(status_code=400, detail="Request ID không hợp lệ")

    coordinator = get_stream_coordinator()
    return await coordinator.cancel_stream(request_id, principal.user_id)


@router.post("/chat-stream")
async def handle_chat_stream(
    req: ChatRequest,
    request: Request,
    x_request_id: Optional[str] = Header(None),
    x_last_sequence: Optional[int] = Header(None, alias="X-Last-Sequence"),
    principal: Principal = Depends(get_current_principal)
):
    """
    Endpoint phát luồng thời gian thực NDJSON Protocol v2 (Decoupled Producer-Consumer):
    - Hỗ trợ resume khi rớt mạng qua header X-Last-Sequence: TUYỆT ĐỐI KHÔNG sinh lại token đã tạo.
    - Hỗ trợ hủy luồng tức thì qua POST /api/chat/{request_id}/cancel.
    - Phát hiện disconnect: dừng gửi về client nhưng bảo lưu buffer cho client resume.
    """
    req_id = set_current_request_id(x_request_id or getattr(request.state, "request_id", None))
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{8,128}", req_id):
        raise HTTPException(status_code=400, detail="X-Request-ID không hợp lệ")
    if x_last_sequence is not None and x_last_sequence < 0:
        raise HTTPException(status_code=400, detail="X-Last-Sequence không hợp lệ")

    history_dicts = [h.model_dump() for h in req.history] if req.history else []
    coordinator = get_stream_coordinator()

    session = await coordinator.get_or_create_stream(
        request_id=req_id,
        owner_id=principal.user_id,
        question=req.question,
        history=history_dicts,
        use_cache=req.enable_cache,
        last_sequence=x_last_sequence,
    )

    return StreamingResponse(
        coordinator.generate_events(
            session=session,
            min_sequence=x_last_sequence or 0,
            is_disconnected_checker=request.is_disconnected,
        ),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
            "X-Request-ID": req_id,
            "X-Stream-ID": session.stream_id,
            "X-Protocol-Version": "2",
        },
    )
