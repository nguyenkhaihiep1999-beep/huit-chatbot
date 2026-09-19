from backend.app.rag.pipeline import _make_artifact_summary


def test_artifact_summary_uses_ready_status_from_manifest():
    summary = _make_artifact_summary(
        {
            "artifact_id": "art_ready_001",
            "title": "Bảng học phí HUIT",
            "svg_url": "/api/artifacts/art_ready_001/preview",
            "manifest": {"render": {"status": "ready"}},
        }
    )

    assert summary is not None
    assert summary["status"] == "ready"


def test_cached_artifact_with_preview_defaults_to_ready():
    summary = _make_artifact_summary(
        {
            "artifact_id": "art_cached_001",
            "title": "Bảng học phí đã lưu cache",
            "preview_url": "/api/artifacts/art_cached_001/preview",
        }
    )

    assert summary is not None
    assert summary["status"] == "ready"
