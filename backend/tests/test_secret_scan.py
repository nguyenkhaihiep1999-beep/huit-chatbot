"""
test_secret_scan.py
Kiểm thử bộ rào chắn quét bí mật (Secret Scanner Quality Gate):
1. Quét toàn bộ repository hiện tại phải PASSED (GO) với 0 real leaks.
2. Kiểm tra quy tắc allowlist dữ liệu giả (synthetic fixtures) mang tính cục bộ, hẹp, không lan truyền.
3. Secret thật xuất hiện ở bất kỳ file nào phải bị phát hiện và trả về FAILED (NO-GO).
4. Secret lạ xuất hiện trong file đã có allowlist vẫn phải bị phát hiện và chặn lại.
5. Không bao giờ in hoặc ghi secret thô ra báo cáo audit_outputs/secret_scan_report.json.
"""
import json
from pathlib import Path
import pytest

from scripts.run_secret_scan import (
    run_scan,
    check_synthetic_allowlist,
    NARROW_SYNTHETIC_ALLOWLIST,
    hash_mask,
    is_placeholder,
    PATTERNS,
)


def test_secret_scan_current_repo_passes(tmp_path):
    """Xác nhận repo hiện tại đạt chất lượng secret scan với 0 real leaks và ghi báo cáo vào tmp_path."""
    out_report = tmp_path / "secret_scan_report.json"
    exit_code = run_scan(output_path=str(out_report))
    assert exit_code == 0

    assert out_report.exists()
    with open(out_report, "r", encoding="utf-8") as fp:
        report = json.load(fp)

    assert report["status"] == "PASSED"
    assert report["real_leaks_count"] == 0
    assert len(report["real_leaks"]) == 0
    assert report["allowlisted_fixtures_count"] == 3


def test_narrow_synthetic_allowlist_matches_only_designated_files():
    """Xác nhận quy tắc allowlist chỉ áp dụng cho đúng file được chỉ định, không cho phép file khác."""
    dummy_key = "sk-" + "1234567890abcdef123456"

    # Trong file được chỉ định: Match
    is_synth, rule_id, _ = check_synthetic_allowlist(
        "backend/tests/test_decision_engine.py",
        "OPENAI_LIKE_KEY",
        dummy_key,
    )
    assert is_synth is True
    assert rule_id == "SYNTH-DECISION-OPENAI-KEY"

    # Trong file khác với cùng chuỗi: Không match (Fail-closed)
    is_synth_other, rule_id_other, _ = check_synthetic_allowlist(
        "backend/app/main.py",
        "OPENAI_LIKE_KEY",
        dummy_key,
    )
    assert is_synth_other is False
    assert rule_id_other is None


def test_narrow_synthetic_allowlist_rejects_different_secret():
    """Xác nhận nếu xuất hiện key lạ dù nằm trong file được allowlist thì vẫn bị từ chối."""
    unauthorized_key = "sk-" + "9999999999999999999999"
    is_synth, _, _ = check_synthetic_allowlist(
        "backend/tests/test_decision_engine.py",
        "OPENAI_LIKE_KEY",
        unauthorized_key,
    )
    assert is_synth is False

    unauthorized_mongo = "mongodb+srv://" + "real_admin:super_secret_pw@cluster.mongodb.net/prod"
    is_synth_mongo, _, _ = check_synthetic_allowlist(
        "backend/tests/test_decision_engine.py",
        "MONGODB_AUTH",
        unauthorized_mongo,
    )
    assert is_synth_mongo is False


def test_real_leak_in_source_code_triggers_scan_failure(tmp_path):
    """Xác nhận secret thật trong workspace tạm thời làm scanner trả về FAILED (NO-GO) với mã thoát 1."""
    # Tạo workspace giả lập
    fake_src = tmp_path / "src"
    fake_src.mkdir()
    leak_file = fake_src / "leaked_service.py"
    leak_key = "sk-" + "abcdef1234567890abcdef1234567890"
    leak_file.write_text(f'API_KEY = "{leak_key}"\n', encoding="utf-8")

    out_report = tmp_path / "test_report.json"
    result_code = run_scan(workspace=str(tmp_path), output_path=str(out_report))

    assert result_code == 1
    assert out_report.exists()
    with open(out_report, "r", encoding="utf-8") as fp:
        data = json.load(fp)

    assert data["status"] == "FAILED"
    assert data["real_leaks_count"] >= 1
    leaked_finding = data["real_leaks"][0]
    assert leaked_finding["file"] == "src/leaked_service.py"
    assert leaked_finding["severity"] == "CRITICAL"
    # Xác nhận secret thô không bị ghi vào masked
    assert leak_key not in leaked_finding["masked"]


def test_scan_report_never_leaks_raw_secret_value(tmp_path):
    """Xác nhận báo cáo audit_outputs không bao giờ ghi lộ chuỗi bí mật đầy đủ."""
    raw_secret = "AIza" + "SyD_fakeGoogleKeyForTest123456789012"
    masked = hash_mask(raw_secret)
    assert raw_secret not in masked
    assert "LEN=" in masked
    assert "SHA256=" in masked


def test_secret_scan_test_does_not_modify_repo_audit_outputs(tmp_path):
    """Regression test: Chạy test secret scan không ghi đè audit_outputs/secret_scan_report.json trong repo."""
    repo_report = Path("audit_outputs/secret_scan_report.json")
    original_mtime = repo_report.stat().st_mtime if repo_report.exists() else None
    original_content = repo_report.read_text(encoding="utf-8") if repo_report.exists() else None

    # Chạy scan với output chuyển hướng sang tmp_path
    temp_report = tmp_path / "custom_scan_report.json"
    code = run_scan(output_path=str(temp_report))
    assert code == 0
    assert temp_report.exists()

    # Báo cáo gốc trong repo không được phép bị thay đổi nội dung hay mtime
    if original_content is not None:
        assert repo_report.exists()
        assert repo_report.stat().st_mtime == original_mtime
        assert repo_report.read_text(encoding="utf-8") == original_content


def test_narrowed_xxx_placeholder_rule_detects_unknown_keys(tmp_path):
    """Regression test: Key lạ chứa substring 'xxx' không được coi là placeholder và phải bị phát hiện (CRITICAL)."""
    # 1. Key lạ chứa 'xxx' ở giữa các ký tự ngẫu nhiên (chuẩn alphanumeric của sk-*)
    unknown_key_with_xxx = "sk-" + "liveapikeyxxx9876543210abcdef"
    assert is_placeholder(unknown_key_with_xxx) is False

    # 2. Key có mặt nạ lặp 'xxxxxx...' (>= 6 ký tự x) thì đúng là placeholder
    masked_placeholder_key = "sk-" + "x" * 24
    assert is_placeholder(masked_placeholder_key) is True

    # 3. Tạo workspace tạm chứa key lạ có 'xxx' và quét kiểm tra
    fake_src = tmp_path / "app"
    fake_src.mkdir()
    leaked_module = fake_src / "external_api.py"
    leaked_module.write_text(f'SERVICE_KEY = "{unknown_key_with_xxx}"\n', encoding="utf-8")

    out_report = tmp_path / "regression_leak_report.json"
    result_code = run_scan(workspace=str(tmp_path), output_path=str(out_report))

    assert result_code == 1
    assert out_report.exists()
    with open(out_report, "r", encoding="utf-8") as fp:
        data = json.load(fp)

    assert data["status"] == "FAILED"
    assert data["real_leaks_count"] == 1
    leak = data["real_leaks"][0]
    assert leak["is_placeholder"] is False
    assert leak["severity"] == "CRITICAL"
    assert unknown_key_with_xxx not in leak["masked"]
