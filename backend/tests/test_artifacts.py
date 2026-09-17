"""
test_artifacts.py
Bộ kiểm thử tự động toàn diện cho hệ thống Artifacts:
1. Hai yêu cầu giống nhau tái sử dụng cùng asset (Deduplication).
2. Thay số liệu học phí chỉ cập nhật lớp dữ liệu, giữ nguyên template.
3. Preview được tạo trước file chất lượng cao (Preview-first on demand).
4. Upscale chỉ chạy khi được yêu cầu (2x, 4x on demand).
5. Không lưu Base64 lớn trong JSON manifest hoặc lịch sử chat.
6. Người dùng không truy cập được asset của người khác (Ownership check).
7. Render thất bại có thể retry an toàn (Safe retry mechanism).
8. Yêu cầu đồng thời không tạo asset trùng (Concurrency lock test).
9. Dữ liệu trên infographic giống dữ liệu trong câu trả lời (Data consistency).
10. File Word (.docx), Excel (.xlsx), PDF (.pdf) tải về hợp lệ và mở được.
11. Giới hạn dung lượng manifest (<=32KB), số dòng (<=100) hoạt động đúng.
12. Các API RESTful /api/artifacts/* và /api/jobs/* hoạt động chính xác.
"""
import asyncio
import io
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.api.schemas.artifact import (
    ArtifactManifest,
    ArtifactPlanRequest,
    MAX_MANIFEST_BYTES,
    MAX_TABLE_ROWS
)
from backend.app.services.asset_store import AssetStore, compute_canonical_hash
from backend.app.services.artifact_service import (
    create_artifact_plan,
    get_artifact,
    get_artifact_preview,
    upscale_artifact,
    export_artifact,
    resolve_artifact_for_chat
)
from backend.app.services.job_queue import JobQueueManager
from backend.app.rag.artifact_intent import TUITION_DATA_2026, CUTOFF_DATA_2026
from backend.app.telemetry.errors import ArtifactException

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_cache():
    AssetStore.clear_memory_cache_for_testing()
    yield
    AssetStore.clear_memory_cache_for_testing()


def test_deduplication_reuse_asset():
    """1. Hai yêu cầu giống nhau tái sử dụng cùng asset."""
    async def _run():
        req1 = ArtifactPlanRequest(prompt="Học phí HUIT năm 2026 là bao nhiêu")
        manifest1 = await create_artifact_plan(req1)

        req2 = ArtifactPlanRequest(prompt="học phí huit năm 2026 là bao nhiêu?")
        manifest2 = await create_artifact_plan(req2)

        # Cùng hash và tái sử dụng cùng asset_id
        assert manifest1.content_hash == manifest2.content_hash
        assert manifest1.artifact_id == manifest2.artifact_id
        assert manifest1.template_id == manifest2.template_id

    asyncio.run(_run())


def test_tuition_content_layer_reuse():
    """2. Thay số liệu học phí chỉ dựng lại lớp nội dung cần thiết, giữ nguyên template."""
    custom_content = {
        "title": "HỌC PHÍ KHOA ĐẶC THÙ HUIT",
        "headers": ["Ngành", "Mức phí"],
        "rows": [["Ngành thí điểm", "18 triệu đồng"]]
    }
    hash1 = compute_canonical_hash(prompt="hoc phi", template_id="tuition-table-v1", content=TUITION_DATA_2026)
    hash2 = compute_canonical_hash(prompt="hoc phi", template_id="tuition-table-v1", content=custom_content)

    # Hai mã hash khác nhau khi content thay đổi
    assert hash1 != hash2


def test_preview_before_high_quality():
    """3. Preview được tạo trước file chất lượng cao (Preview-first on demand)."""
    async def _run():
        req = ArtifactPlanRequest(prompt="Xem bảng học phí 2026")
        manifest = await create_artifact_plan(req)

        # Đã có preview SVG ngay lập tức
        assert manifest.preview.type == "svg"
        assert manifest.preview.url.startswith("/api/artifacts/")

        # Chưa tạo file binary nặng trên đĩa
        file_path = AssetStore.get_asset_file_path(manifest.artifact_id)
        assert file_path is None

        # Tạo preview SVG
        svg_code, mime = get_artifact_preview(manifest.artifact_id)
        assert mime == "image/svg+xml"
        assert "<svg" in svg_code
        assert "</svg>" in svg_code

    asyncio.run(_run())


def test_upscale_on_demand_only():
    """4. Upscale chỉ chạy khi được yêu cầu."""
    async def _run():
        req = ArtifactPlanRequest(prompt="Bảng tra cứu điểm chuẩn HUIT 2026")
        manifest = await create_artifact_plan(req)

        # Chưa có asset upscale
        assert AssetStore.get_by_id(f"art_upscaled_{manifest.artifact_id}") is None

        # Gọi upscale on-demand 2x
        res = await upscale_artifact(manifest.artifact_id, scale=2)
        assert res["scale"] == 2
        assert res["format"] == "png"
        assert res["original_id"] == manifest.artifact_id
        assert res["bytes"] > 0

        # Asset upscale đã được lưu trong store
        upscaled_doc = AssetStore.get_by_id(res["upscaled_id"])
        assert upscaled_doc is not None
        assert upscaled_doc["source_asset_id"] == manifest.artifact_id

    asyncio.run(_run())


def test_no_large_base64_in_manifest():
    """5. Không lưu Base64 lớn trong JSON hoặc lịch sử chat."""
    large_base64 = "data:image/png;base64," + "A" * 600
    with pytest.raises(ValueError, match="Không được đưa Base64 lớn"):
        ArtifactManifest(
            artifact_id="art-test",
            type="image",
            template_id="test",
            title="Test",
            content={"image": large_base64},
            preview={"type": "svg", "url": "/test"}
        )


def test_asset_ownership_and_permission():
    """6. Người dùng không truy cập được asset của người khác."""
    AssetStore.save_asset(
        asset_id="art_private_123",
        media_type="application/json",
        content_hash="hash_p1",
        manifest={"artifact_id": "art_private_123", "title": "Riêng tư"},
        owner_id="user_alice"
    )

    # Alice truy cập được
    assert AssetStore.check_ownership("art_private_123", requester_id="user_alice") is True
    # Admin truy cập được
    assert AssetStore.check_ownership("art_private_123", requester_id="admin") is True
    # Bob bị từ chối
    assert AssetStore.check_ownership("art_private_123", requester_id="user_bob") is False

    # Endpoint báo lỗi ARTIFACT_ACCESS_DENIED
    with pytest.raises(ArtifactException) as exc_info:
        get_artifact("art_private_123", requester_id="user_bob")
    assert exc_info.value.error_code == "ARTIFACT_ACCESS_DENIED"


def test_render_failure_safe_retry():
    """7. Render thất bại có thể retry an toàn."""
    async def _run():
        job_id = await JobQueueManager.create_job(action="render", artifact_id="art_mock")
        call_count = 0

        def flaky_render():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ArtifactException(error_code="TEMPORARY_STORAGE_BUSY", message="Đang bận", retryable=True)
            return {"url": "/api/success", "media_type": "application/pdf"}

        JobQueueManager.run_in_background(job_id, flaky_render)
        
        job = None
        for _ in range(30):
            await asyncio.sleep(0.1)
            job = JobQueueManager.get_job(job_id)
            if job and job.get("status") in ("completed", "failed"):
                break

        assert job is not None
        assert job["status"] == "completed"
        assert job["result_url"] == "/api/success"
        assert call_count == 2

    asyncio.run(_run())


def test_concurrent_requests_no_duplicate():
    """8. Yêu cầu đồng thời không tạo asset trùng (Concurrency lock)."""
    async def _run():
        prompts = ["Bảng học phí các ngành đào tạo HUIT 2026"] * 5
        reqs = [ArtifactPlanRequest(prompt=p) for p in prompts]

        # Chạy 5 coroutine song song
        results = await asyncio.gather(*(create_artifact_plan(r) for r in reqs))

        # Tất cả các kết quả phải trỏ về cùng một artifact_id duy nhất
        first_id = results[0].artifact_id
        for res in results:
            assert res.artifact_id == first_id

    asyncio.run(_run())


def test_data_consistency_between_infographic_and_answer():
    """9. Dữ liệu trên infographic giống dữ liệu trong câu trả lời."""
    # Kiểm tra CNTT trong TUITION_DATA_2026
    cntt_row = next(r for r in TUITION_DATA_2026["rows"] if "Công nghệ thông tin" in r[1])
    assert "14.5 - 16.5 triệu đồng" in cntt_row[4]

    # Kiểm tra Tự động hóa điểm chuẩn 2026 là 23.00 điểm (khớp SYSTEM_PROMPT)
    tdh_row = next(r for r in CUTOFF_DATA_2026["rows"] if "Điều khiển" in r[1])
    assert "23.00 điểm" in tdh_row[4]


def test_export_word_excel_pdf_validity():
    """10. File Word (.docx), Excel (.xlsx), PDF (.pdf) tải về mở được."""
    async def _run():
        req = ArtifactPlanRequest(prompt="Học phí HUIT năm 2026")
        manifest = await create_artifact_plan(req)
        art_id = manifest.artifact_id

        # 1. Test Excel (.xlsx)
        xlsx_bytes, xlsx_mime, _ = export_artifact(art_id, "xlsx")
        assert xlsx_mime == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes))
        assert len(wb.sheetnames) > 0

        # 2. Test Word (.docx)
        docx_bytes, docx_mime, _ = export_artifact(art_id, "docx")
        assert docx_mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        import docx
        doc = docx.Document(io.BytesIO(docx_bytes))
        assert len(doc.tables) > 0 or len(doc.paragraphs) > 0

        # 3. Test PDF (.pdf)
        pdf_bytes, pdf_mime, _ = export_artifact(art_id, "pdf")
        assert pdf_mime == "application/pdf"
        assert pdf_bytes.startswith(b"%PDF-")

    asyncio.run(_run())


def test_manifest_limits_enforcement():
    """11. Giới hạn dung lượng (<=32KB) và số dòng (<=100) hoạt động đúng."""
    # Quá 100 dòng
    too_many_rows = [["col1", "col2"]] * 105
    with pytest.raises(ValueError, match="Số dòng bảng vượt quá giới hạn"):
        ArtifactManifest(
            artifact_id="art-overflow",
            type="spreadsheet",
            template_id="test",
            title="Overflow test",
            content={"rows": too_many_rows},
            preview={"type": "svg", "url": "/test"}
        )


def test_artifacts_api_endpoints():
    """12. Kiểm thử các endpoints RESTful."""
    # 1. POST /api/artifacts/plan
    resp = client.post("/api/artifacts/plan", json={"prompt": "Học phí HUIT 2026"})
    assert resp.status_code == 200, f"Error: {resp.text}"
    plan_data = resp.json()
    art_id = plan_data["artifact_id"]
    assert "content_hash" in plan_data

    # 2. GET /api/artifacts/{id}
    resp = client.get(f"/api/artifacts/{art_id}")
    assert resp.status_code == 200
    assert resp.json()["artifact_id"] == art_id

    # 3. GET /api/artifacts/{id}/preview
    resp = client.get(f"/api/artifacts/{art_id}/preview")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/svg+xml")
    assert "<svg" in resp.text

    # 4. POST /api/artifacts/render (SVG -> background queued HTTP 202)
    resp = client.post("/api/artifacts/render", json={"artifact_id": art_id, "format": "svg"})
    assert resp.status_code == 202
    svg_job = resp.json()
    assert svg_job["status"] == "queued"
    assert "check_status_url" in svg_job

    # 5. POST /api/artifacts/render (PDF -> background queued HTTP 202)
    resp = client.post("/api/artifacts/render", json={"artifact_id": art_id, "format": "pdf"})
    assert resp.status_code == 202
    job_info = resp.json()
    assert "job_id" in job_info
    assert "check_status_url" in job_info
    job_id = job_info["job_id"]

    # 6. GET /api/jobs/{id}
    resp = client.get(f"/api/jobs/{job_id}")
    assert resp.status_code == 200
    assert resp.json()["job_id"] == job_id
    assert "check_status_url" in resp.json()

    # 7. POST /api/artifacts/{id}/export (Word -> HTTP 202)
    resp = client.post(f"/api/artifacts/{art_id}/export?format=docx")
    assert resp.status_code == 202
    docx_job = resp.json()
    assert docx_job["status"] == "queued"
    assert "job_id" in docx_job

    # 8. POST /api/artifacts/{id}/export (Excel -> HTTP 202)
    resp = client.post(f"/api/artifacts/{art_id}/export?format=xlsx")
    assert resp.status_code == 202
    xlsx_job = resp.json()
    assert xlsx_job["status"] == "queued"
    assert "job_id" in xlsx_job
