"""
Unit tests kiểm thử toàn diện tầng StreamCoordinator Service và FastAPI Chat Route:
1. Tạo stream mới (NDJSON protocol v2, header, sequence).
2. Reconnect sau gián đoạn.
3. Resume theo sequence (không gọi lại LLM / generator).
4. Duplicate request ID với payload khác (409 Conflict).
5. Cross-owner access (403 Forbidden khi truy cập/hủy stream của người khác).
6. Cancel stream (gửi tín hiệu hủy, phát sự kiện cancelled).
7. Disconnect handling (dừng consumer nhưng bảo lưu buffer cho resume).
8. Redis unavailable fallback (vận hành hoàn toàn in-memory khi Redis offline).
9. Stream terminal state (không sinh lại task khi stream đã hoàn tất).
10. Cleanup expired session (prune các session quá hạn TTL).
"""
import asyncio
import json
import time
from unittest.mock import patch, MagicMock, AsyncMock
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.stream_coordinator import (
    get_stream_coordinator,
    StreamSession,
    compute_request_signature,
)
from backend.app.api.dependencies.auth import get_current_principal, Principal

client = TestClient(app)


def mock_stream_events(*args, **kwargs):
    """Giả lập chuỗi sự kiện NDJSON chuẩn từ pipeline."""
    events = [
        {"type": "start", "sequence": 1, "payload": {"version": "2.0.0"}},
        {"type": "progress", "sequence": 2, "payload": {"sources": [{"i": 1, "title": "huit_tuyensinh"}]}},
        {"type": "token", "sequence": 3, "payload": {"token": "Điểm", "delta": "Điểm"}},
        {"type": "token", "sequence": 4, "payload": {"token": "chuẩn", "delta": "chuẩn"}},
        {"type": "token", "sequence": 5, "payload": {"token": "2026", "delta": "2026"}},
        {"type": "done", "sequence": 6, "payload": {"latency_ms": 42, "cached": False}},
    ]
    for ev in events:
        yield json.dumps(ev) + "\n"


@pytest.fixture(autouse=True)
def reset_stream_registry():
    coordinator = get_stream_coordinator()
    coordinator.active_streams.clear()
    yield
    coordinator.active_streams.clear()


# 1. Tạo stream mới
def test_create_new_stream_success():
    req_id = "req_test_coord_new_01"
    with patch("backend.app.services.stream_coordinator.stream_answer", side_effect=mock_stream_events):
        resp = client.post(
            "/api/chat-stream",
            json={"question": "Xét học bạ ngành Công nghệ Thông tin?"},
            headers={"X-Request-ID": req_id}
        )

        assert resp.status_code == 200
        assert resp.headers.get("X-Protocol-Version") == "2"
        assert resp.headers.get("X-Request-ID") == req_id
        assert resp.headers.get("X-Stream-ID") == req_id
        assert "application/x-ndjson" in resp.headers.get("content-type", "")

        lines = [l.strip() for l in resp.text.strip().split("\n") if l.strip()]
        assert len(lines) == 6

        events = [json.loads(l) for l in lines]
        assert events[0]["type"] in ("start", "stream_started")
        assert events[0]["sequence"] == 1
        assert events[-1]["type"] in ("done", "completed")
        assert events[-1]["sequence"] == 6


# 2. Reconnect sau gián đoạn
def test_reconnect_after_interruption():
    req_id = "req_test_coord_reconnect_02"
    with patch("backend.app.services.stream_coordinator.stream_answer", side_effect=mock_stream_events):
        # Lần 1: client nhận được đến sequence 2 thì rớt mạng
        resp1 = client.post(
            "/api/chat-stream",
            json={"question": "Xét học bạ ngành Kỹ thuật Thực phẩm?"},
            headers={"X-Request-ID": req_id}
        )
        assert resp1.status_code == 200

        # Lần 2: Reconnect với X-Last-Sequence = 2
        resp2 = client.post(
            "/api/chat-stream",
            json={"question": "Xét học bạ ngành Kỹ thuật Thực phẩm?"},
            headers={"X-Request-ID": req_id, "X-Last-Sequence": "2"}
        )
        assert resp2.status_code == 200

        lines = [l.strip() for l in resp2.text.strip().split("\n") if l.strip()]
        assert len(lines) == 4
        seqs = [json.loads(l)["sequence"] for l in lines]
        assert seqs == [3, 4, 5, 6]


# 3. Resume theo sequence không gọi lại LLM / generator
def test_resume_by_sequence_does_not_duplicate_llm_call():
    req_id = "req_test_coord_resume_03"
    mock_spy = MagicMock(side_effect=mock_stream_events)

    with patch("backend.app.services.stream_coordinator.stream_answer", mock_spy):
        # Lần 1: stream ban đầu
        resp1 = client.post(
            "/api/chat-stream",
            json={"question": "Học phí đại học HUIT?"},
            headers={"X-Request-ID": req_id}
        )
        assert resp1.status_code == 200
        assert mock_spy.call_count == 1

        # Lần 2: Resume sau sequence 4
        resp2 = client.post(
            "/api/chat-stream",
            json={"question": "Học phí đại học HUIT?"},
            headers={"X-Request-ID": req_id, "X-Last-Sequence": "4"}
        )
        assert resp2.status_code == 200

        # Đảm bảo tuyệt đối không gọi lại generator
        assert mock_spy.call_count == 1

        lines = [l.strip() for l in resp2.text.strip().split("\n") if l.strip()]
        assert len(lines) == 2
        seqs = [json.loads(l)["sequence"] for l in lines]
        assert seqs == [5, 6]


# 4. Duplicate request ID với payload khác -> 409 Conflict
def test_duplicate_request_id_with_different_payload_returns_409():
    req_id = "req_test_coord_dup_payload_04"
    with patch("backend.app.services.stream_coordinator.stream_answer", side_effect=mock_stream_events):
        # Tạo stream ban đầu với câu hỏi A
        resp1 = client.post(
            "/api/chat-stream",
            json={"question": "Chỉ tiêu ngành Ngôn ngữ Anh?"},
            headers={"X-Request-ID": req_id}
        )
        assert resp1.status_code == 200

        # Gửi cùng request_id nhưng câu hỏi B khác hoàn toàn
        resp2 = client.post(
            "/api/chat-stream",
            json={"question": "Chỉ tiêu ngành Kế toán kiểm toán?"},
            headers={"X-Request-ID": req_id}
        )
        assert resp2.status_code == 409
        assert "Request ID đã được dùng cho nội dung khác" in resp2.json()["detail"]


# 5. Cross-owner access -> 403 Forbidden
def test_cross_owner_access_forbidden():
    req_id = "req_test_coord_owner_05"
    coordinator = get_stream_coordinator()

    # Giả lập stream được tạo bởi User A
    signature = compute_request_signature("Ký túc xá HUIT?", [], True)
    session = StreamSession(req_id, owner_id="user_alice_123", request_signature=signature)
    session.buffer = [json.dumps({"type": "start", "sequence": 1, "payload": {"version": "2.0.0"}}) + "\n"]
    session.is_completed = True
    coordinator.active_streams[req_id] = session

    # User B cố tình resume stream của User A
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        user_id="user_bob_456",
        is_authenticated=True,
        session_id="sess_bob",
    )

    try:
        # Cố gắng đọc stream
        resp_read = client.post(
            "/api/chat-stream",
            json={"question": "Ký túc xá HUIT?"},
            headers={"X-Request-ID": req_id}
        )
        assert resp_read.status_code == 403
        assert "Bạn không có quyền tiếp tục stream này" in resp_read.json()["detail"]

        # Cố gắng hủy stream
        resp_cancel = client.post(f"/api/chat/{req_id}/cancel")
        assert resp_cancel.status_code == 403
        assert "Bạn không có quyền hủy stream này" in resp_cancel.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_current_principal, None)


# 6. Cancel stream
def test_cancel_stream_workflow():
    req_id = "req_test_coord_cancel_06"

    def slow_generator(*args, **kwargs):
        yield json.dumps({"type": "start", "sequence": 1, "payload": {"version": "2.0.0"}}) + "\n"
        yield json.dumps({"type": "token", "sequence": 2, "payload": {"token": "Đang phân tích..."}}) + "\n"
        for i in range(3, 30):
            time.sleep(0.05)
            yield json.dumps({"type": "token", "sequence": i, "payload": {"token": f"token_{i}"}}) + "\n"

    with patch("backend.app.services.stream_coordinator.stream_answer", side_effect=slow_generator):
        coordinator = get_stream_coordinator()
        signature = compute_request_signature("Chương trình chất lượng cao?", [], True)
        session = StreamSession(req_id, owner_id="anonymous", request_signature=signature)
        coordinator.active_streams[req_id] = session

        # Hủy stream
        cancel_resp = client.post(f"/api/chat/{req_id}/cancel")
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["success"] is True
        assert session.abort_event.is_set()


# 7. Disconnect handling
@pytest.mark.anyio
async def test_disconnect_preserves_buffer_for_resume():
    coordinator = get_stream_coordinator()
    req_id = "req_test_coord_disc_07"
    session = StreamSession(req_id, owner_id="anonymous", request_signature="sig_test")
    session.buffer = [
        json.dumps({"type": "start", "sequence": 1, "payload": {"version": "2.0.0"}}) + "\n",
        json.dumps({"type": "token", "sequence": 2, "payload": {"token": "HUIT"}}) + "\n",
    ]
    coordinator.active_streams[req_id] = session

    # Giả lập disconnect ngay trước khi đọc event thứ 3
    is_disconnected_calls = [False, True]

    async def mock_is_disconnected():
        return is_disconnected_calls.pop(0) if is_disconnected_calls else True

    received_lines = []
    async for line in coordinator.generate_events(
        session=session,
        min_sequence=0,
        is_disconnected_checker=mock_is_disconnected,
    ):
        received_lines.append(line)

    # Đã nhận các dòng trong buffer
    assert len(received_lines) == 2
    # Buffer trong session vẫn nguyên vẹn
    assert len(session.buffer) == 2


# 8. Redis unavailable fallback
def test_redis_unavailable_fallback():
    req_id = "req_test_coord_redis_down_08"

    with patch("backend.app.services.stream_coordinator.get_async_redis_client", return_value=None):
        with patch("backend.app.services.stream_coordinator.stream_answer", side_effect=mock_stream_events):
            resp = client.post(
                "/api/chat-stream",
                json={"question": "Địa chỉ cơ sở chính HUIT?"},
                headers={"X-Request-ID": req_id}
            )

            assert resp.status_code == 200
            lines = [l.strip() for l in resp.text.strip().split("\n") if l.strip()]
            assert len(lines) == 6

            # Hủy khi Redis down vẫn hoạt động an toàn trong memory
            cancel_resp = client.post(f"/api/chat/{req_id}/cancel")
            assert cancel_resp.status_code == 200


# 9. Stream terminal state
def test_stream_terminal_state():
    req_id = "req_test_coord_terminal_09"
    coordinator = get_stream_coordinator()
    signature = compute_request_signature("Học phí học kỳ hè?", [], True)

    session = StreamSession(req_id, owner_id="anonymous", request_signature=signature)
    session.buffer = [
        json.dumps({"type": "start", "sequence": 1, "payload": {"version": "2.0.0"}}) + "\n",
        json.dumps({"type": "done", "sequence": 2, "payload": {"latency_ms": 10}}) + "\n",
    ]
    session.is_completed = True
    coordinator.active_streams[req_id] = session

    mock_producer = MagicMock(side_effect=mock_stream_events)
    with patch("backend.app.services.stream_coordinator.stream_answer", mock_producer):
        resp = client.post(
            "/api/chat-stream",
            json={"question": "Học phí học kỳ hè?"},
            headers={"X-Request-ID": req_id}
        )

        assert resp.status_code == 200
        # Không sinh task hay gọi LLM mới
        assert mock_producer.call_count == 0
        lines = [l.strip() for l in resp.text.strip().split("\n") if l.strip()]
        assert len(lines) == 2


# 10. Cleanup expired session
@pytest.mark.anyio
async def test_prune_expired_sessions():
    coordinator = get_stream_coordinator()
    now = 10000.0

    # Session 1: Đã hoàn tất và quá hạn (> 300s)
    s_expired = StreamSession("req_exp", "anon", "sig1")
    s_expired.is_completed = True
    s_expired.created_at = now - 350
    coordinator.active_streams["req_exp"] = s_expired

    # Session 2: Đã hoàn tất nhưng chưa quá hạn (< 300s)
    s_recent = StreamSession("req_rec", "anon", "sig2")
    s_recent.is_completed = True
    s_recent.created_at = now - 50
    coordinator.active_streams["req_rec"] = s_recent

    # Session 3: Đang chạy (is_completed = False) dù tạo từ lâu
    s_active = StreamSession("req_act", "anon", "sig3")
    s_active.is_completed = False
    s_active.created_at = now - 400
    coordinator.active_streams["req_act"] = s_active

    pruned_count = await coordinator.prune_expired_streams(now=now)

    assert pruned_count == 1
    assert "req_exp" not in coordinator.active_streams
    assert "req_rec" in coordinator.active_streams
    assert "req_act" in coordinator.active_streams
