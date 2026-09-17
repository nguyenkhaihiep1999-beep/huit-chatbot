import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Dict, List, Callable, Awaitable, Tuple
from fastapi import HTTPException
from backend.app.rag.pipeline import stream_answer
from backend.app.cache.redis_client import get_async_redis_client

logger = logging.getLogger("huit_chatbot.stream_coordinator")

_MAX_ACTIVE_STREAMS = 200
_STREAM_TTL_SECONDS = 300


class StreamSession:
    """Phiên quản lý luồng phát sinh câu trả lời bất đồng bộ tách biệt Producer-Consumer."""

    def __init__(self, request_id: str, owner_id: str = "anonymous", request_signature: str = ""):
        self.request_id = request_id
        self.stream_id = request_id
        self.owner_id = owner_id
        self.request_signature = request_signature
        self.buffer: List[str] = []
        self.subscribers: List[asyncio.Queue] = []
        self.abort_event = asyncio.Event()
        self.is_completed = False
        self.terminal_event_sent = False
        self.created_at = time.time()
        self.producer_task: Optional[asyncio.Task] = None

    def add_subscriber(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self.subscribers.append(q)
        return q

    def remove_subscriber(self, q: asyncio.Queue):
        if q in self.subscribers:
            self.subscribers.remove(q)

    async def broadcast(self, event_str: Optional[str]):
        if event_str is not None:
            # Đảm bảo duy nhất một terminal event (Terminal Exactly Once)
            try:
                parsed = json.loads(event_str.strip())
                evt_type = parsed.get("type")
                if evt_type in ("done", "completed", "error", "cancelled"):
                    if self.terminal_event_sent:
                        return
                    self.terminal_event_sent = True
            except Exception:
                pass
            self.buffer.append(event_str)
        for q in list(self.subscribers):
            await q.put(event_str)


def compute_request_signature(question: str, history: List[dict], use_cache: bool) -> str:
    raw = json.dumps(
        {"question": question.strip(), "history": history, "use_cache": bool(use_cache)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def stream_keys(stream_id: str) -> Tuple[str, str, str]:
    return (
        f"stream_buf:{stream_id}",
        f"stream_meta:{stream_id}",
        f"stream_cancel:{stream_id}",
    )


def canonical_control_event(event_type: str, sequence: int, session: StreamSession, payload: dict) -> str:
    from backend.app.api.schemas.streaming_v2 import create_ndjson_v2_event
    return create_ndjson_v2_event(
        event_type=event_type,
        sequence=sequence,
        stream_id=session.stream_id,
        request_id=session.request_id,
        payload=payload,
    )


async def persist_stream_event(redis_client, stream_id: str, event_line: str) -> None:
    if redis_client is None:
        return
    buffer_key, meta_key, _ = stream_keys(stream_id)
    try:
        await redis_client.rpush(buffer_key, event_line)
        await redis_client.expire(buffer_key, _STREAM_TTL_SECONDS)
        await redis_client.expire(meta_key, _STREAM_TTL_SECONDS)
    except Exception as exc:
        logger.warning("Không thể lưu stream event vào Redis: %s", type(exc).__name__)


async def persist_stream_meta(redis_client, session: StreamSession, status: str) -> None:
    if redis_client is None:
        return
    _, meta_key, cancel_key = stream_keys(session.stream_id)
    try:
        await redis_client.hset(meta_key, mapping={
            "owner_id": session.owner_id,
            "request_signature": session.request_signature,
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        await redis_client.expire(meta_key, _STREAM_TTL_SECONDS)
        await redis_client.expire(cancel_key, _STREAM_TTL_SECONDS)
    except Exception as exc:
        logger.warning("Không thể lưu stream metadata vào Redis: %s", type(exc).__name__)


async def restore_stream_from_redis(
    redis_client,
    stream_id: str,
    owner_id: str,
    request_signature: str,
) -> Optional[StreamSession]:
    if redis_client is None:
        return None
    buffer_key, meta_key, _ = stream_keys(stream_id)
    try:
        meta = await redis_client.hgetall(meta_key)
        if not meta:
            return None
        if meta.get("owner_id") != owner_id:
            raise HTTPException(status_code=403, detail="Bạn không có quyền tiếp tục stream này")
        if meta.get("request_signature") != request_signature:
            raise HTTPException(status_code=409, detail="Request ID đã được dùng cho nội dung khác")
        session = StreamSession(stream_id, owner_id, request_signature)
        session.buffer = list(await redis_client.lrange(buffer_key, 0, -1))
        session.is_completed = meta.get("status") in {"completed", "cancelled", "failed"}
        return session
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Không thể phục hồi stream từ Redis: %s", type(exc).__name__)
        return None


async def relay_redis_stream(session: StreamSession) -> None:
    """Theo dõi buffer Redis do instance khác sản xuất mà không gọi lại LLM."""
    redis_client = get_async_redis_client()
    if redis_client is None:
        session.is_completed = True
        await session.broadcast(None)
        return
    buffer_key, meta_key, _ = stream_keys(session.stream_id)
    cursor = len(session.buffer)
    try:
        while not session.abort_event.is_set():
            rows = await redis_client.lrange(buffer_key, cursor, -1)
            for row in rows:
                cursor += 1
                await session.broadcast(row)
            meta = await redis_client.hgetall(meta_key)
            if not meta or meta.get("status") in {"completed", "cancelled", "failed"}:
                break
            await asyncio.sleep(0.25)
    finally:
        session.is_completed = True
        await session.broadcast(None)


def _get_stream_answer_fn():
    import sys
    coord_mod = sys.modules.get("backend.app.services.stream_coordinator")
    if coord_mod and hasattr(coord_mod, "stream_answer"):
        return getattr(coord_mod, "stream_answer")
    return stream_answer


async def run_producer(
    session: StreamSession,
    question: str,
    history: List[dict],
    use_cache: bool,
    owner_id: Optional[str]
):
    """Tiến trình Producer sinh token nền độc lập với vòng lặp đọc của client."""
    from backend.app.api.schemas.streaming_v2 import convert_legacy_to_canonical, LEGACY_TO_CANONICAL_MAP

    loop = asyncio.get_running_loop()
    redis_client = get_async_redis_client()
    _, _, cancel_key = stream_keys(session.stream_id)
    final_status = "completed"

    await persist_stream_meta(redis_client, session, "active")

    try:
        answer_fn = _get_stream_answer_fn()
        gen = answer_fn(
            question=question,
            chat_history=history,
            use_cache=use_cache,
            request_id=session.request_id,
            owner_id=owner_id
        )

        while True:
            redis_cancelled = False
            if redis_client is not None:
                try:
                    redis_cancelled = bool(await redis_client.get(cancel_key))
                except Exception:
                    redis_cancelled = False
            if session.abort_event.is_set() or redis_cancelled:
                final_status = "cancelled"
                cancel_event = canonical_control_event(
                    "cancelled",
                    len(session.buffer) + 1,
                    session,
                    {"detail": "Yêu cầu đã được hủy bởi người dùng"},
                )
                await session.broadcast(cancel_event)
                await persist_stream_event(redis_client, session.stream_id, cancel_event)
                break

            line = await loop.run_in_executor(None, lambda: next(gen, None))
            if line is None:
                break

            # Compatibility boundary: chuyển đổi legacy event từ generator bên ngoài/mock nếu có
            try:
                parsed = json.loads(line.strip())
                raw_type = parsed.get("type", "")
                if raw_type in LEGACY_TO_CANONICAL_MAP and raw_type != "done":
                    canon_dict = convert_legacy_to_canonical(parsed)
                    canon_dict["stream_id"] = session.stream_id
                    canon_dict["request_id"] = session.request_id
                    canon_dict["sequence"] = len(session.buffer) + 1
                    line = json.dumps(canon_dict, ensure_ascii=False) + "\n"
            except Exception:
                pass

            await session.broadcast(line)
            await persist_stream_event(redis_client, session.stream_id, line)

            # Nhường microtask cho event loop
            await asyncio.sleep(0.002)

    except Exception as e:
        final_status = "failed"
        logger.error("Lỗi producer stream %s: %s", session.request_id, type(e).__name__)
        err_event = canonical_control_event(
            "error",
            len(session.buffer) + 1,
            session,
            {"error_code": "STREAM_PRODUCER_FAILED", "message": "Sự cố trong quá trình sinh luồng.", "retryable": True},
        )
        await session.broadcast(err_event)
        await persist_stream_event(redis_client, session.stream_id, err_event)
    finally:
        session.is_completed = True
        await persist_stream_meta(redis_client, session, final_status)
        await session.broadcast(None)


class StreamCoordinator:
    """Service điều phối toàn diện các phiên phát luồng câu trả lời (Stream Sessions)."""

    def __init__(self, max_active_streams: int = _MAX_ACTIVE_STREAMS, ttl_seconds: int = _STREAM_TTL_SECONDS):
        self._active_streams: Dict[str, StreamSession] = {}
        self._streams_lock = asyncio.Lock()
        self._max_active_streams = max_active_streams
        self._ttl_seconds = ttl_seconds

    @property
    def active_streams(self) -> Dict[str, StreamSession]:
        return self._active_streams

    async def prune_expired_streams(self, now: Optional[float] = None) -> int:
        """Dọn dẹp các phiên stream đã hoàn thành quá thời hạn TTL."""
        current_time = now if now is not None else time.time()
        async with self._streams_lock:
            expired_keys = [
                k for k, sess in self._active_streams.items()
                if sess.is_completed and (current_time - sess.created_at > self._ttl_seconds)
            ]
            for k in expired_keys:
                self._active_streams.pop(k, None)
            return len(expired_keys)

    async def get_or_create_stream(
        self,
        request_id: str,
        owner_id: str,
        question: str,
        history: List[dict],
        use_cache: bool,
        last_sequence: Optional[int] = None,
    ) -> StreamSession:
        """
        Khởi tạo hoặc kết nối lại phiên stream:
        - Kiểm tra ownership & request signature.
        - Khôi phục từ Redis nếu client yêu cầu resume khi rớt mạng.
        - Điều phối producer task hoặc Redis relay task nền.
        """
        signature = compute_request_signature(question, history, use_cache)
        await self.prune_expired_streams()

        async with self._streams_lock:
            session = self._active_streams.get(request_id)

        if session is not None:
            if session.owner_id != owner_id:
                raise HTTPException(status_code=403, detail="Bạn không có quyền tiếp tục stream này")
            if session.request_signature and session.request_signature != signature:
                raise HTTPException(status_code=409, detail="Request ID đã được dùng cho nội dung khác")
            return session

        redis_client = get_async_redis_client()
        restored = None
        if last_sequence is not None and last_sequence > 0:
            restored = await restore_stream_from_redis(redis_client, request_id, owner_id, signature)
            if restored is None:
                raise HTTPException(
                    status_code=409,
                    detail="Không còn buffer để tiếp tục stream; hãy gửi một request ID mới",
                )

        async with self._streams_lock:
            session = self._active_streams.get(request_id)
            if session is not None:
                if session.owner_id != owner_id:
                    raise HTTPException(status_code=403, detail="Bạn không có quyền tiếp tục stream này")
                if session.request_signature and session.request_signature != signature:
                    raise HTTPException(status_code=409, detail="Request ID đã được dùng cho nội dung khác")
                return session

            active_count = sum(1 for item in self._active_streams.values() if not item.is_completed)
            if active_count >= self._max_active_streams:
                raise HTTPException(status_code=503, detail="Hệ thống đang xử lý quá nhiều stream")

            session = restored or StreamSession(request_id, owner_id, signature)
            self._active_streams[request_id] = session

            if restored is not None:
                if not session.is_completed:
                    session.producer_task = asyncio.create_task(relay_redis_stream(session))
            else:
                if redis_client is not None:
                    buffer_key, meta_key, cancel_key = stream_keys(request_id)
                    try:
                        await redis_client.delete(buffer_key, meta_key, cancel_key)
                    except Exception as exc:
                        logger.warning("Không thể dọn buffer stream cũ: %s", type(exc).__name__)
                session.producer_task = asyncio.create_task(
                    run_producer(session, question, history, use_cache, owner_id)
                )

        return session

    async def generate_events(
        self,
        session: StreamSession,
        min_sequence: int = 0,
        is_disconnected_checker: Optional[Callable[[], Awaitable[bool]]] = None,
    ):
        """
        Bộ sinh sự kiện NDJSON bất đồng bộ cho StreamingResponse:
        1. Gửi lại các sự kiện có sẵn trong buffer có sequence > min_sequence.
        2. Lắng nghe các sự kiện mới từ hàng đợi subscriber.
        3. Phát hiện ngắt kết nối an toàn bảo toàn buffer.
        """
        min_seq = min_sequence or 0
        subscriber_q = session.add_subscriber()

        try:
            # 1. Gửi các sự kiện đã sinh sẵn trong buffer mà client chưa nhận (sequence > min_seq)
            sent_sequences = set()
            for buffered_line in list(session.buffer):
                try:
                    parsed = json.loads(buffered_line.strip())
                    seq_num = parsed.get("sequence", 0)
                    if seq_num > min_seq:
                        sent_sequences.add(seq_num)
                        yield buffered_line
                except Exception:
                    yield buffered_line

            # Nếu session đã hoàn tất từ trước, dừng ngay mà không đợi queue
            if session.is_completed:
                return

            # 2. Tiếp tục đọc các sự kiện mới từ queue của subscriber
            while True:
                if is_disconnected_checker is not None and await is_disconnected_checker():
                    logger.info("Client ngắt kết nối cho request_id=%s, giữ phiên stream cho resume.", session.request_id)
                    break

                try:
                    line = await asyncio.wait_for(subscriber_q.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    if session.is_completed:
                        break
                    continue

                if line is None:
                    # Producer đã hoàn thành
                    break

                # Bỏ qua nếu sự kiện này đã được gửi từ buffer ở bước 1
                try:
                    parsed = json.loads(line.strip())
                    seq_num = parsed.get("sequence", 0)
                    if seq_num in sent_sequences or seq_num <= min_seq:
                        continue
                    sent_sequences.add(seq_num)
                except Exception:
                    pass

                yield line

        finally:
            session.remove_subscriber(subscriber_q)

    async def cancel_stream(self, request_id: str, owner_id: str) -> dict:
        """Hủy phiên stream đang hoạt động theo request_id và owner_id."""
        async with self._streams_lock:
            session = self._active_streams.get(request_id)

        if session:
            if session.owner_id != owner_id:
                raise HTTPException(status_code=403, detail="Bạn không có quyền hủy stream này")
            if not session.is_completed:
                session.abort_event.set()
                logger.info("Đã phát tín hiệu hủy cho stream %s", request_id)
                return {"success": True, "message": f"Đã gửi tín hiệu hủy cho yêu cầu {request_id}"}

        redis_client = get_async_redis_client()
        if redis_client is not None:
            _, meta_key, cancel_key = stream_keys(request_id)
            try:
                meta = await redis_client.hgetall(meta_key)
                if meta:
                    if meta.get("owner_id") != owner_id:
                        raise HTTPException(status_code=403, detail="Bạn không có quyền hủy stream này")
                    if meta.get("status") == "active":
                        await redis_client.set(cancel_key, "1", ex=self._ttl_seconds)
                        return {"success": True, "message": f"Đã gửi tín hiệu hủy cho yêu cầu {request_id}"}
            except HTTPException:
                raise
            except Exception as exc:
                logger.warning("Không thể gửi tín hiệu hủy qua Redis: %s", type(exc).__name__)

        return {"success": False, "message": f"Không tìm thấy yêu cầu đang xử lý với ID {request_id}"}


_COORDINATOR_INSTANCE: Optional[StreamCoordinator] = None


def get_stream_coordinator() -> StreamCoordinator:
    """Singleton getter cho StreamCoordinator service."""
    global _COORDINATOR_INSTANCE
    if _COORDINATOR_INSTANCE is None:
        _COORDINATOR_INSTANCE = StreamCoordinator()
    return _COORDINATOR_INSTANCE
