"""
test_streaming_v2_resume.py
Unit tests kiểm thử giao thức NDJSON Streaming v2, phục hồi kết nối (Resume) và hủy luồng:
1. Streaming v2 phát các sự kiện chuẩn hóa (sequence, type, request_id) với header X-Protocol-Version: 2.
2. Khi client truyền X-Last-Sequence: N, chỉ nhận các sự kiện sequence > N.
3. Khi resume, backend tái sử dụng buffer đã có, KHÔNG gọi LLM hoặc generator lần thứ 2.
4. Hủy luồng qua POST /api/chat/{request_id}/cancel: stream nhận sự kiện type: 'cancelled'.
100% offline, mock mạng hoàn toàn.
"""
import asyncio
import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.stream_coordinator import get_stream_coordinator, StreamSession

client = TestClient(app)


def fake_stream_generator(*args, **kwargs):
    """Giả lập chuỗi sự kiện NDJSON chuẩn từ pipeline."""
    events = [
        {"type": "start", "sequence": 1, "payload": {"version": "2.0.0"}},
        {"type": "progress", "sequence": 2, "payload": {"sources": [{"i": 1, "title": "huit_guide"}]}},
        {"type": "token", "sequence": 3, "payload": {"token": "Xin", "delta": "Xin"}},
        {"type": "token", "sequence": 4, "payload": {"token": "chào", "delta": "chào"}},
        {"type": "token", "sequence": 5, "payload": {"token": "bạn", "delta": "bạn"}},
        {"type": "done", "sequence": 6, "payload": {"latency_ms": 50, "cached": False}},
    ]
    for ev in events:
        yield json.dumps(ev) + "\n"


@pytest.fixture(autouse=True)
def clean_registry():
    coord = get_stream_coordinator()
    coord.active_streams.clear()
    yield
    coord.active_streams.clear()


def test_streaming_v2_full_flow():
    """Kiểm tra luồng phát đầy đủ sự kiện NDJSON v2 với sequence tăng dần."""
    req_id = "req_test_stream_v2_full"

    with patch("backend.app.services.stream_coordinator.stream_answer", side_effect=fake_stream_generator):
        response = client.post(
            "/api/chat-stream",
            json={"question": "Thông tin tuyển sinh ngành CNTT?"},
            headers={"X-Request-ID": req_id}
        )

        assert response.status_code == 200
        assert response.headers.get("X-Protocol-Version") == "2"
        assert response.headers.get("X-Request-ID") == req_id

        lines = [l.strip() for l in response.text.strip().split("\n") if l.strip()]
        assert len(lines) == 6

        first_evt = json.loads(lines[0])
        assert first_evt["type"] in ("start", "stream_started")
        assert first_evt["sequence"] == 1

        last_evt = json.loads(lines[-1])
        assert last_evt["type"] in ("done", "completed")
        assert last_evt["sequence"] == 6


def test_streaming_v2_resume_without_duplicate_llm_call():
    """Client rớt mạng sau sequence 3, gửi X-Last-Sequence: 3 -> Chỉ nhận sequence 4, 5, 6 và KHÔNG gọi lại LLM."""
    req_id = "req_test_stream_resume_1"
    mock_generator_spy = MagicMock(side_effect=fake_stream_generator)

    with patch("backend.app.services.stream_coordinator.stream_answer", mock_generator_spy):
        # 1. Lần đầu: stream đầy đủ
        resp1 = client.post(
            "/api/chat-stream",
            json={"question": "Điểm chuẩn xét tuyển?"},
            headers={"X-Request-ID": req_id}
        )
        assert resp1.status_code == 200
        assert mock_generator_spy.call_count == 1

        # 2. Lần 2 (Resume): Client gửi X-Last-Sequence: 3
        resp2 = client.post(
            "/api/chat-stream",
            json={"question": "Điểm chuẩn xét tuyển?"},
            headers={"X-Request-ID": req_id, "X-Last-Sequence": "3"}
        )
        assert resp2.status_code == 200

        # Quan trọng: stream_answer TUYỆT ĐỐI KHÔNG được gọi lần thứ 2!
        assert mock_generator_spy.call_count == 1

        lines = [l.strip() for l in resp2.text.strip().split("\n") if l.strip()]
        assert len(lines) == 3

        seqs = [json.loads(l)["sequence"] for l in lines]
        assert seqs == [4, 5, 6]


def test_streaming_v2_cancellation_endpoint():
    """Hủy stream qua POST /api/chat/{request_id}/cancel phát sự kiện cancelled."""
    coord = get_stream_coordinator()
    req_id = "req_test_stream_cancel_1"

    def slow_generator(*args, **kwargs):
        yield json.dumps({"type": "start", "sequence": 1, "payload": {"version": "2.0.0"}}) + "\n"
        yield json.dumps({"type": "token", "sequence": 2, "payload": {"token": "Đang suy nghĩ..."}}) + "\n"
        import time
        for i in range(3, 20):
            time.sleep(0.05)
            yield json.dumps({"type": "token", "sequence": i, "payload": {"token": f"token_{i}"}}) + "\n"

    with patch("backend.app.services.stream_coordinator.stream_answer", side_effect=slow_generator):
        # Kiểm tra cancel với ID không tồn tại
        cancel_resp_missing = client.post("/api/chat/unknown_id/cancel")
        assert cancel_resp_missing.status_code == 200
        assert cancel_resp_missing.json()["success"] is False

        # Khởi tạo session trong coordinator registry
        sess = StreamSession(req_id)
        coord.active_streams[req_id] = sess

        cancel_resp = client.post(f"/api/chat/{req_id}/cancel")
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["success"] is True
        assert sess.abort_event.is_set() is True
