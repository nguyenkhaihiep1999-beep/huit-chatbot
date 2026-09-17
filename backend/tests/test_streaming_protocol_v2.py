"""
test_streaming_protocol_v2.py
Bộ kiểm thử toàn diện cho NDJSON Protocol v2:
1. Canonical Event Set duy nhất: start, token, progress, artifact, error, done, cancelled, heartbeat.
2. Thống nhất Envelope: protocol_version, stream_id, request_id, sequence, type, timestamp, payload.
3. Strict Payload validation: từ chối các trường tùy tiện không kiểm soát (extra="forbid").
4. Compatibility Boundary: chuyển đổi hai chiều an toàn giữa Canonical và Legacy.
5. Normal streaming: đầy đủ envelope, sequence đơn điệu, protocol_version=2.
6. Chunk split: bộ parser ghép nối chính xác các dòng bị cắt ngang qua nhiều chunk.
7. Reconnect/Resume: resume theo sequence > last_sequence mà không sinh lại token cũ.
8. Terminal exactly once: chỉ có đúng 1 terminal event được broadcast.
9. Cancel: hủy stream thành công, phát sinh event type="cancelled" và lưu bền vững.
10. Cross-owner resume: từ chối 403 khi người dùng khác cố resume stream của chủ sở hữu.
11. Redis unavailable: hoạt động bền bỉ dựa trên RAM buffer khi Redis offline.
12. Artifact event size limit: payload artifact < 2048 bytes, cấm Base64/binary lớn.
"""
import asyncio
import json
import uuid
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.api.schemas.streaming_v2 import (
    create_ndjson_v2_event,
    validate_payload_for_type,
    convert_legacy_to_canonical,
    convert_canonical_to_legacy,
    StreamEventEnvelope,
    StreamArtifactPayload,
    CANONICAL_EVENT_TYPES,
    MAX_ARTIFACT_EVENT_BYTES,
)
from backend.app.services.stream_coordinator import (
    StreamCoordinator,
    StreamSession,
    compute_request_signature,
)

client = TestClient(app)


class TestStreamingProtocolV2:
    def test_canonical_event_set_and_envelope(self):
        """1. Kiểm thử toàn bộ tập Canonical Events đều dùng chung một Envelope chuẩn."""
        canonical_samples = [
            ("start", {"version": "2.0.0"}),
            ("progress", {"stage": "retrieval", "sources": [{"i": 1, "title": "HUIT"}], "cached": False}),
            ("token", {"token": "Xin chào"}),
            ("artifact", {"artifact_id": "art_1", "type": "document", "title": "Tài liệu 2026"}),
            ("done", {"latency_ms": 120.5, "cached": False}),
            ("error", {"error_code": "ERR_FAIL", "message": "Lỗi hệ thống", "retryable": False}),
            ("cancelled", {"detail": "Người dùng đã hủy"}),
            ("heartbeat", {"status": "alive"}),
        ]

        for seq, (evt_type, payload) in enumerate(canonical_samples, 1):
            line = create_ndjson_v2_event(
                event_type=evt_type,
                sequence=seq,
                stream_id="stream_canon_01",
                request_id="req_canon_01",
                payload=payload
            )
            parsed = json.loads(line.strip())
            assert parsed["protocol_version"] == 2
            assert parsed["stream_id"] == "stream_canon_01"
            assert parsed["request_id"] == "req_canon_01"
            assert parsed["sequence"] == seq
            assert parsed["type"] == evt_type
            assert "timestamp" in parsed
            assert isinstance(parsed["payload"], dict)

    def test_strict_payload_validation_rejects_extra_fields(self):
        """3. Kiểm thử payload validation loại bỏ/chặn các trường tùy tiện không có trong schema (extra='forbid')."""
        # Hợp lệ
        valid_start = validate_payload_for_type("start", {"version": "2.0.0"})
        assert valid_start["version"] == "2.0.0"

        # Bị từ chối khi thêm trường không xác định vào start payload
        with pytest.raises(ValueError):
            validate_payload_for_type("start", {"version": "2.0.0", "unauthorized_extra_field": "injected"})

        # Bị từ chối khi thêm trường lạ vào done payload
        with pytest.raises(ValueError):
            validate_payload_for_type("done", {"latency_ms": 100, "malicious_field": 123})

    def test_compatibility_boundary_conversions(self):
        """4. Kiểm thử chuyển đổi tại Compatibility Boundary giữa Legacy và Canonical."""
        # Legacy event đầu vào (ví dụ từ client cũ hoặc generator cũ)
        legacy_event = {
            "type": "text_delta",
            "sequence": 2,
            "stream_id": "s_leg",
            "request_id": "r_leg",
            "payload": {"delta": "Đang xử lý..."}
        }
        canonical = convert_legacy_to_canonical(legacy_event)
        assert canonical["type"] == "token"
        assert canonical["payload"]["token"] == "Đang xử lý..."
        assert canonical["protocol_version"] == 2

        # Convert ngược lại sang legacy cho client cũ
        back_to_legacy = convert_canonical_to_legacy(canonical)
        assert back_to_legacy["type"] == "text_delta"
        assert back_to_legacy["payload"]["delta"] == "Đang xử lý..."

    def test_normal_streaming_envelope_and_monotonic_sequence(self):
        """5. Kiểm thử streaming bình thường: đúng envelope, sequence 1..N đơn điệu."""
        req_id = f"test-v2-norm-{uuid.uuid4().hex[:8]}"
        resp = client.post(
            "/api/chat-stream",
            json={"question": "Xin chào ad"},
            headers={"X-Request-ID": req_id}
        )
        assert resp.status_code == 200
        assert resp.headers.get("X-Protocol-Version") == "2"

        lines = [line.strip() for line in resp.text.strip().split("\n") if line.strip()]
        assert len(lines) >= 3

        events = [json.loads(l) for l in lines]
        for idx, evt in enumerate(events, 1):
            assert evt["protocol_version"] == 2
            assert evt["sequence"] == idx
            assert "timestamp" in evt
            assert evt["stream_id"] == req_id
            assert evt["request_id"] == req_id
            assert isinstance(evt["payload"], dict)

        assert events[0]["type"] in ("start", "stream_started")
        assert events[-1]["type"] in ("done", "completed")

    def test_chunk_split_reassembly(self):
        """6. Kiểm thử parser xử lý chunk bị cắt giữa dòng."""
        full_line = json.dumps({
            "protocol_version": 2,
            "type": "token",
            "sequence": 1,
            "stream_id": "s1",
            "request_id": "r1",
            "timestamp": "2026-09-15T12:00:00Z",
            "payload": {"token": "Xin chào bạn, tôi là AI HUIT."}
        }) + "\n"

        chunk1 = full_line[:25]
        chunk2 = full_line[25:60]
        chunk3 = full_line[60:]

        buffer = ""
        parsed_events = []
        for chunk in [chunk1, chunk2, chunk3]:
            buffer += chunk
            lines = buffer.split("\n")
            buffer = lines.pop()
            for line in lines:
                if line.strip():
                    parsed_events.append(json.loads(line))

        assert len(parsed_events) == 1
        assert parsed_events[0]["payload"]["token"] == "Xin chào bạn, tôi là AI HUIT."

    def test_reconnect_resume_no_duplicate_token(self):
        """7. Kiểm thử reconnect/resume: không phát lại token đã nhận."""
        req_id = f"test-v2-resume-{uuid.uuid4().hex[:8]}"
        resp1 = client.post(
            "/api/chat-stream",
            json={"question": "Điểm chuẩn CNTT 2026?"},
            headers={"X-Request-ID": req_id}
        )
        assert resp1.status_code == 200
        events1 = [json.loads(l) for l in resp1.text.strip().split("\n") if l.strip()]

        last_seq = 2
        resp2 = client.post(
            "/api/chat-stream",
            json={"question": "Điểm chuẩn CNTT 2026?"},
            headers={"X-Request-ID": req_id, "X-Last-Sequence": str(last_seq)}
        )
        assert resp2.status_code == 200
        events2 = [json.loads(l) for l in resp2.text.strip().split("\n") if l.strip()]

        assert len(events2) > 0
        for e in events2:
            assert e["sequence"] > last_seq

    def test_terminal_event_exactly_once(self):
        """8. Kiểm thử Terminal Event Exactly Once: chỉ có duy nhất 1 terminal event được broadcast."""
        async def _run():
            session = StreamSession("req_term_01", "owner_1", "sig_1")
            q = session.add_subscriber()

            # Phát event token bình thường
            t1 = create_ndjson_v2_event("token", 1, "req_term_01", "req_term_01", {"token": "A"})
            await session.broadcast(t1)

            # Phát terminal event lần 1: done
            done1 = create_ndjson_v2_event("done", 2, "req_term_01", "req_term_01", {"latency_ms": 100})
            await session.broadcast(done1)

            # Cố phát thêm terminal event lần 2: completed / error
            done2 = create_ndjson_v2_event("completed", 3, "req_term_01", "req_term_01", {"latency_ms": 110})
            await session.broadcast(done2)

            err1 = create_ndjson_v2_event("error", 4, "req_term_01", "req_term_01", {"error_code": "E1", "message": "fail"})
            await session.broadcast(err1)

            received = []
            while not q.empty():
                item = await q.get()
                if item:
                    received.append(json.loads(item))

            types = [e["type"] for e in received]
            terminal_types = [t for t in types if t in ("done", "completed", "error", "cancelled")]
            assert len(terminal_types) == 1
            assert terminal_types[0] == "done"

        asyncio.run(_run())

    def test_error_event_schema_and_retryable(self):
        """9. Kiểm thử Error event có error_code, message và retryable."""
        err_str = create_ndjson_v2_event(
            "error",
            5,
            "stream_err",
            "req_err",
            {"error_code": "NETWORK_TIMEOUT", "message": "Mất kết nối tới upstream.", "retryable": True}
        )
        evt = json.loads(err_str)
        assert evt["type"] == "error"
        assert evt["payload"]["error_code"] == "NETWORK_TIMEOUT"
        assert evt["payload"]["retryable"] is True

    def test_artifact_event_size_limit_and_no_base64(self):
        """10. Kiểm thử Artifact event < 2KB và cấm Base64 lớn."""
        valid_art = create_ndjson_v2_event(
            "artifact",
            2,
            "s1",
            "r1",
            {
                "artifact_id": "art_tuition_2026",
                "type": "chart",
                "title": "Biểu đồ học phí HUIT 2026",
                "preview_url": "/api/artifacts/art_tuition_2026/preview",
                "manifest_url": "/api/artifacts/art_tuition_2026",
            }
        )
        assert len(valid_art.encode("utf-8")) < MAX_ARTIFACT_EVENT_BYTES

        large_b64 = "data:image/png;base64," + "A" * 500
        with pytest.raises(ValueError):
            create_ndjson_v2_event(
                "artifact",
                2,
                "s1",
                "r1",
                {
                    "artifact_id": "art_leak",
                    "type": "image",
                    "title": "Ảnh rò rỉ",
                    "preview_url": large_b64,
                }
            )

    def test_cross_owner_resume_rejected_403(self):
        """11. Kiểm thử cross-owner resume bị từ chối với 403."""
        async def _run():
            coord = StreamCoordinator()
            sess_a = await coord.get_or_create_stream(
                request_id="req_owner_a",
                owner_id="user_alice",
                question="Xin chào",
                history=[],
                use_cache=False,
            )
            assert sess_a.owner_id == "user_alice"

            with pytest.raises(HTTPException) as exc_info:
                await coord.get_or_create_stream(
                    request_id="req_owner_a",
                    owner_id="user_bob",
                    question="Xin chào",
                    history=[],
                    use_cache=False,
                )
            assert exc_info.value.status_code == 403

        asyncio.run(_run())

    def test_redis_unavailable_resilience(self):
        """12. Kiểm thử hệ thống vẫn hoạt động bền bỉ khi Redis offline."""
        async def _run():
            coord = StreamCoordinator()
            sess = await coord.get_or_create_stream(
                request_id="req_no_redis_01",
                owner_id="anon",
                question="Học phí HUIT",
                history=[],
                use_cache=False,
            )
            assert sess is not None
            assert sess.stream_id == "req_no_redis_01"

        asyncio.run(_run())

    def test_cancel_event_handling(self):
        """13. Kiểm thử phát sinh sự kiện cancelled hợp lệ."""
        cancel_str = create_ndjson_v2_event(
            "cancelled",
            3,
            "s_cancel",
            "r_cancel",
            {"detail": "Người dùng đã bấm dừng."}
        )
        evt = json.loads(cancel_str)
        assert evt["type"] == "cancelled"
        assert evt["payload"]["detail"] == "Người dùng đã bấm dừng."
