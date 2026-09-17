import json
import uuid
import pytest
from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)

def test_ndjson_protocol_v2_structure():
    """Kiểm tra cấu trúc NDJSON Protocol v2: sequence 1..N, timestamp, terminal event."""
    req_id = f"test-stream-{uuid.uuid4().hex[:8]}"
    response = client.post(
        "/api/chat-stream",
        json={"question": "Xin chào ad"},
        headers={"X-Request-ID": req_id}
    )
    assert response.status_code == 200
    assert response.headers.get("X-Protocol-Version") == "2"

    lines = [line.strip() for line in response.text.strip().split("\n") if line.strip()]
    assert len(lines) >= 3

    events = [json.loads(line) for line in lines]

    # Kiểm tra tính đơn điệu của sequence và protocol_version
    for i, evt in enumerate(events, 1):
        assert evt.get("protocol_version") == 2
        assert evt.get("sequence") == i
        assert "timestamp" in evt
        assert evt.get("request_id") == req_id

    # Sự kiện đầu tiên phải là start (hoặc stream_started legacy), thứ 2 là progress (hoặc meta)
    assert events[0]["type"] in ("start", "stream_started")
    assert events[1]["type"] in ("progress", "meta")

    # Sự kiện cuối cùng phải là done (hoặc completed)
    assert events[-1]["type"] in ("done", "completed")
    assert "latency_ms" in events[-1]["payload"]

def test_ndjson_protocol_v2_resume_buffer():
    """Kiểm tra khôi phục luồng qua X-Last-Sequence (Resume Buffer)."""
    req_id = f"test-resume-{uuid.uuid4().hex[:8]}"

    # Bước 1: Gọi stream ban đầu để lấp đầy buffer trên server
    resp1 = client.post(
        "/api/chat-stream",
        json={"question": "Xin chào ad"},
        headers={"X-Request-ID": req_id}
    )
    assert resp1.status_code == 200
    events1 = [json.loads(line) for line in resp1.text.strip().split("\n") if line.strip()]
    assert len(events1) >= 3

    # Bước 2: Gọi resume với sequence = 2
    resume_seq = 2
    resp2 = client.post(
        "/api/chat-stream",
        json={"question": "Xin chào ad"},
        headers={
            "X-Request-ID": req_id,
            "X-Last-Sequence": str(resume_seq)
        }
    )
    assert resp2.status_code == 200
    events2 = [json.loads(line) for line in resp2.text.strip().split("\n") if line.strip()]
    
    # Chỉ nhận lại các sự kiện có sequence > 2
    assert len(events2) > 0
    for evt in events2:
        assert evt.get("sequence") > resume_seq

def test_ndjson_protocol_v2_planned_artifact_events():
    """Kiểm tra phát sinh sự kiện artifact khi câu hỏi có infographic / danh mục."""
    req_id = f"test-artifact-{uuid.uuid4().hex[:8]}"
    response = client.post(
        "/api/chat-stream",
        json={"question": "Học phí các ngành năm 2026 thế nào?"},
        headers={"X-Request-ID": req_id}
    )
    assert response.status_code == 200
    lines = [line.strip() for line in response.text.strip().split("\n") if line.strip()]
    events = [json.loads(line) for line in lines]

    event_types = [evt["type"] for evt in events]
    assert any(t in event_types for t in ("start", "stream_started"))
    assert any(t in event_types for t in ("progress", "meta"))
    assert any(t in event_types for t in ("artifact", "artifact_planned"))
    assert any(t in event_types for t in ("token", "text_delta"))
    assert any(t in event_types for t in ("done", "completed"))
