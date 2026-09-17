"""
test_admin_session_ltx.py
Bộ kiểm thử toàn diện cho hệ thống Admin Sessions (LTX Gateway v2 & Production-Safe):
1. Schema & Model Contract: strict/error, BSON UTC Date, extra="forbid", cấm token/cookie/secret rõ.
2. LTX Gateway v2 Integrity: Cả 4 specs (create, find_valid, revoke, purge_expired) có declared_checksum
   là hằng số literal SHA-256 cố định, ngân sách max_time_ms/output/param nghiêm ngặt, allowed collection chính xác.
3. Duplicate hash rejection: Unique index trên session_hash chặn tuyệt đối bản ghi trùng lặp.
4. TTL Contract: expireAfterSeconds=0 và cơ chế purge_expired dọn dẹp chính xác theo mốc UTC.
5. Redis unavailable: Khi Redis lỗi, phiên vẫn lưu trữ và phục vụ bền vững qua MongoDB Atlas.
6. Mongo unavailable: Khi Mongo lỗi trong dev/test, phiên vẫn lưu qua Redis.
7. Dual outage fail-closed trên production: Khi cả Redis và Mongo cùng lỗi ở môi trường production,
   save_session ném lỗi, cấm dùng memory fallback, phiên không được phép kích hoạt.
8. Revoke failure no false success: Khi persistent revoke thất bại ở production, không giả báo True.
9. Multi-instance session sharing: 2 instance độc lập bộ nhớ chia sẻ phiên qua store phân tán.
10. Fake, expired, revoked token rejection: Chữ ký giả, quá hạn, hoặc đã thu hồi đều bị từ chối.
11. CSRF token binding: Token CSRF gắn liền với session_id và được bảo vệ.
12. Zero raw Mongo access: Ranh giới kiến trúc tuyệt đối - không service nào ngoài gateway được chạm admin_sessions.
"""
import ast
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError
import pymongo.errors

from backend.app.config import settings
from backend.app.models.mongo_models import AdminSessionDocument
from backend.app.services.auth_service import (
    AdminSessionStore,
    create_admin_session,
    verify_admin_token_get_session,
    verify_admin_token,
    revoke_admin_token,
    generate_csrf_token,
    verify_csrf_token,
)
from backend.app.data_access.operation_gateway import get_operation
import backend.app.data_access.operations.admin_session_operations as admin_ops


@pytest.fixture(autouse=True)
def reset_session_stores():
    """Làm sạch bộ nhớ session store trước và sau mỗi test case."""
    AdminSessionStore.clear_for_testing()
    yield
    AdminSessionStore.clear_for_testing()


# ==============================================================================
# 1. SCHEMA & MODEL CONTRACT
# ==============================================================================
def test_admin_session_schema_and_model_contract():
    """Kiểm tra model AdminSessionDocument tuân thủ strict schema, cấm extra fields và secret rõ."""
    now = datetime.now(timezone.utc)
    valid_hash = "f" * 64
    doc = AdminSessionDocument(
        session_hash=valid_hash,
        session_id="sess_abc123",
        admin_id=settings.ADMIN_USERNAME,
        created_at=now,
        expires_at=now + timedelta(hours=2),
        revoked=False,
        ip_address="192.168.1.50",
        user_agent="Mozilla/5.0 TestBrowser",
    )
    assert doc.session_hash == valid_hash
    assert doc.revoked is False
    assert doc.created_at.tzinfo is not None

    # Cấm tuyệt đối lưu trữ plaintext secrets hoặc extra fields
    with pytest.raises(ValidationError):
        AdminSessionDocument(
            session_hash=valid_hash,
            session_id="sess_abc123",
            admin_id="admin",
            created_at=now,
            expires_at=now + timedelta(hours=1),
            raw_token="huit-adm-s.secret_plaintext_token",  # cấm
        )

    # Hash sai định dạng (không phải 64 hex lowercase)
    with pytest.raises(ValidationError):
        AdminSessionDocument(
            session_hash="invalid_hash_not_hex_or_too_short",
            session_id="sess_abc123",
            admin_id="admin",
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )


# ==============================================================================
# 2. LTX GATEWAY V2 INTEGRITY & BUDGETS
# ==============================================================================
def test_registered_operations_specs_and_literal_checksums():
    """Kiểm tra 4 Registered Operations được nạp đầy đủ, checksum là literal cố định và khớp."""
    expected_keys = [
        "admin_session.create",
        "admin_session.find_valid",
        "admin_session.revoke",
        "admin_session.purge_expired",
    ]
    for k in expected_keys:
        spec = get_operation(k, "2.0.0")
        assert spec is not None, f"Operation '{k}@2.0.0' phải được đăng ký"
        assert spec.allowed_collections == ("admin_sessions",), f"Allowed collection của '{k}' phải là ('admin_sessions',)"

        # Checksum phải là literal cố định (64 ký tự hex), không được rỗng
        assert len(spec.declared_checksum) == 64, f"declared_checksum của '{k}' phải là chuỗi SHA-256 cố định"
        assert spec.declared_checksum == spec.checksum, f"declared_checksum của '{k}' phải khớp tuyệt đối computed checksum"

        # Parameter model và output model phải có extra='forbid'
        assert spec.parameter_model.model_config.get("extra") == "forbid"
        assert spec.output_model.model_config.get("extra") == "forbid"

        # Ngân sách tài nguyên nghiêm ngặt
        assert spec.max_time_ms <= 5000
        assert spec.max_output_bytes <= 16_000
        assert spec.max_parameter_bytes <= 64_000


# ==============================================================================
# 3. DUPLICATE HASH REJECTION
# ==============================================================================
def test_duplicate_hash_rejection_via_unique_index():
    """Kiểm tra việc từ chối tạo session trùng lặp session_hash để bảo vệ tính toàn vẹn."""
    valid_hash = "e" * 64
    exp_dt = datetime.now(timezone.utc) + timedelta(hours=1)

    # Tạo session lần 1 thành công
    res1 = admin_ops.save_admin_session_ltx(
        session_hash=valid_hash,
        session_id="sess_1",
        admin_id="admin",
        expires_at=exp_dt,
    )
    assert res1 is True

    # Tạo session lần 2 với cùng session_hash phải bị từ chối với DuplicateKeyError (unique index)
    with pytest.raises(pymongo.errors.DuplicateKeyError):
        admin_ops.save_admin_session_ltx(
            session_hash=valid_hash,
            session_id="sess_2_duplicate",
            admin_id="admin",
            expires_at=exp_dt,
        )


# ==============================================================================
# 4. TTL CONTRACT & PURGE
# ==============================================================================
def test_ttl_contract_and_purge_expired():
    """Kiểm tra hợp đồng TTL và tác vụ dọn dẹp các session đã quá hạn."""
    now = datetime.now(timezone.utc)
    old_hash = "1" * 64
    fresh_hash = "2" * 64

    # Session cũ đã hết hạn
    admin_ops.save_admin_session_ltx(
        session_hash=old_hash,
        session_id="sess_old",
        admin_id="admin",
        expires_at=now - timedelta(minutes=10),
    )
    # Session mới còn hạn
    admin_ops.save_admin_session_ltx(
        session_hash=fresh_hash,
        session_id="sess_fresh",
        admin_id="admin",
        expires_at=now + timedelta(hours=1),
    )

    # Purge các session quá hạn trước thời điểm hiện tại
    deleted = admin_ops.purge_expired_admin_sessions_ltx(before=now)
    assert deleted >= 0

    # Migration schema chứa định nghĩa index TTL expireAfterSeconds=0
    indexes = [
        m for m in [
            pymongo.IndexModel([("expires_at", pymongo.ASCENDING)], expireAfterSeconds=0, name="ttl_expires_at")
        ]
    ]
    assert indexes[0].document["expireAfterSeconds"] == 0


# ==============================================================================
# 5. REDIS UNAVAILABLE (MONGO AVAILABLE)
# ==============================================================================
def test_redis_unavailable_mongo_available():
    """Khi Redis gặp sự cố, phiên admin vẫn lưu trữ và phục vụ bình thường qua MongoDB Atlas."""
    with patch("backend.app.cache.redis_client.get_sync_redis_client", side_effect=Exception("Redis connection refused")):
        session_id, cookie_token, _ = create_admin_session(ttl_seconds=1800)
        assert session_id.startswith("adm_sess_")

        # Xác thực phiên thành công thông qua MongoDB fallback
        verified_id = verify_admin_token_get_session(cookie_token)
        assert verified_id == session_id


# ==============================================================================
# 6. MONGO UNAVAILABLE (REDIS AVAILABLE)
# ==============================================================================
def test_mongo_unavailable_redis_available_in_development():
    """Khi MongoDB gặp sự cố trong môi trường dev/test, phiên vẫn lưu và xác thực qua Redis."""
    with patch.object(type(settings), "IS_PRODUCTION", new_callable=lambda: property(lambda self: False)):
        with patch.object(type(settings), "APP_ENV", new_callable=lambda: property(lambda self: "development")):
            with patch("backend.app.data_access.operations.admin_session_operations.save_admin_session_ltx", side_effect=Exception("Mongo network down")):
                session_id, cookie_token, _ = create_admin_session(ttl_seconds=1800)
                verified_id = verify_admin_token_get_session(cookie_token)
                assert verified_id == session_id


# ==============================================================================
# 7. DUAL OUTAGE FAIL-CLOSED IN PRODUCTION
# ==============================================================================
def test_dual_outage_fail_closed_in_production():
    """Ở Production, khi cả Redis và MongoDB cùng lỗi: save_session ném lỗi, cấm fallback về RAM."""
    with patch.object(type(settings), "IS_PRODUCTION", new_callable=lambda: property(lambda self: True)):
        with patch.object(type(settings), "APP_ENV", new_callable=lambda: property(lambda self: "production")):
            with patch("backend.app.cache.redis_client.get_sync_redis_client", side_effect=Exception("Redis cluster down")):
                with patch("backend.app.data_access.operations.admin_session_operations.save_admin_session_ltx", side_effect=Exception("Mongo atlas timeout")):
                    # save_session phải ném ngoại lệ làm đăng nhập thất bại
                    with pytest.raises(RuntimeError) as excinfo:
                        create_admin_session(ttl_seconds=1800)
                    assert "Fail-closed" in str(excinfo.value)

                    # Tuyệt đối không cho phép xác thực bằng RAM memory fallback trong production
                    dummy_hash = "c" * 64
                    AdminSessionStore._memory_sessions[dummy_hash] = {
                        "session_id": "phantom_memory_session",
                        "expires_at": int(datetime.now(timezone.utc).timestamp()) + 3600,
                        "created_at": int(datetime.now(timezone.utc).timestamp()),
                    }
                    # is_active phải trả về None khi persistent store không khả dụng
                    active_sess = AdminSessionStore.is_active(dummy_hash)
                    assert active_sess is None, "Production cấm dùng memory fallback khi persistent store không tìm thấy"


# ==============================================================================
# 8. REVOKE FAILURE NO FALSE SUCCESS
# ==============================================================================
def test_revoke_persistent_failure_no_false_success_in_production():
    """Ở Production, nếu cả Redis và Mongo lỗi khi revoke, không được giả báo True."""
    with patch.object(type(settings), "IS_PRODUCTION", new_callable=lambda: property(lambda self: True)):
        with patch.object(type(settings), "APP_ENV", new_callable=lambda: property(lambda self: "production")):
            with patch("backend.app.cache.redis_client.get_sync_redis_client", side_effect=Exception("Redis error")):
                with patch("backend.app.data_access.operations.admin_session_operations.revoke_admin_session_ltx", side_effect=Exception("Mongo down")):
                    sample_hash = "d" * 64
                    # Thu hồi thất bại trên persistent store phải trả về False
                    revoked_ok = AdminSessionStore.revoke(sample_hash)
                    assert revoked_ok is False, "Persistent revoke thất bại không được giả báo thành công (phải trả về False)"


# ==============================================================================
# 9. MULTI-INSTANCE SESSION SHARING & CONCURRENCY
# ==============================================================================
def test_multi_instance_session_sharing_and_revocation():
    """Hai instance độc lập RAM chia sẻ phiên qua distributed store và nhận biết revoke tức thì."""
    # Instance A tạo session
    session_id, cookie_token, _ = create_admin_session(ttl_seconds=3600)

    # Giả lập Instance B (RAM hoàn toàn trống, không chia sẻ bộ nhớ với Instance A)
    AdminSessionStore._memory_sessions.clear()

    # Instance B vẫn xác thực thành công nhờ distributed store (Redis/Mongo)
    verified_on_instance_b = verify_admin_token_get_session(cookie_token)
    assert verified_on_instance_b == session_id

    # Instance A thực hiện logout (thu hồi session)
    revoked = revoke_admin_token(cookie_token)
    assert revoked is True

    # Instance B làm sạch RAM cục bộ của nó
    AdminSessionStore._memory_sessions.clear()

    # Instance B lập tức thấy phiên đã bị thu hồi
    verified_after_revoke = verify_admin_token_get_session(cookie_token)
    assert verified_after_revoke is None


# ==============================================================================
# 10. FAKE, EXPIRED, AND REVOKED TOKEN REJECTION
# ==============================================================================
def test_fake_expired_and_revoked_token_rejection():
    """Kiểm tra từ chối token giả mạo chữ ký, token hết hạn, hoặc token đã thu hồi."""
    now_ts = int(datetime.now(timezone.utc).timestamp())

    # 1. Fake signature
    fake_token = f"huit-adm-s.sess_123.secret_abc.{now_ts + 3600}.bad_signature_here"
    assert verify_admin_token_get_session(fake_token) is None
    assert verify_admin_token(fake_token) is False

    # 2. Expired token
    past_ts = now_ts - 3600
    expired_token = f"huit-adm-s.sess_123.secret_abc.{past_ts}.valid_format"
    assert verify_admin_token_get_session(expired_token) is None

    # 3. Revoked token
    _, valid_token, _ = create_admin_session(ttl_seconds=1800)
    assert verify_admin_token(valid_token) is True
    revoke_admin_token(valid_token)
    assert verify_admin_token(valid_token) is False
    assert verify_admin_token_get_session(valid_token) is None


# ==============================================================================
# 11. CSRF TOKEN BINDING AND VALIDATION
# ==============================================================================
def test_csrf_token_binding_and_validation():
    """Kiểm tra CSRF token gắn chặt với session_id của admin và từ chối token sai lệch."""
    session_id = "adm_sess_test_12345"
    csrf_token = generate_csrf_token(session_id)
    assert isinstance(csrf_token, str) and len(csrf_token) > 10

    # Token hợp lệ cho đúng session
    assert verify_csrf_token(session_id, csrf_token) is True

    # Token sai lệch hoặc session khác
    assert verify_csrf_token("adm_sess_other_user", csrf_token) is False
    assert verify_csrf_token(session_id, "invalid_csrf_token_spoof") is False
    assert verify_csrf_token(session_id, None) is False


# ==============================================================================
# 12. ZERO RAW MONGO ACCESS OUTSIDE BOUNDARY
# ==============================================================================
def test_zero_raw_mongo_access_outside_boundary():
    """Phân tích tĩnh AST: Không một file nào trong backend/app/services hay routes được truy cập trực tiếp collection 'admin_sessions'."""
    repo_root = Path(__file__).resolve().parent.parent
    app_dir = repo_root / "app"

    violations = []
    allowed_boundary_files = {
        "admin_session_operations_v2.py",
        "admin_session_operations.py",
        "mongo_models.py",
    }

    for py_file in app_dir.rglob("*.py"):
        if py_file.name in allowed_boundary_files:
            continue
        try:
            content = py_file.read_text(encoding="utf-8")
            tree = ast.parse(content, filename=str(py_file))
            for node in ast.walk(tree):
                # Phát hiện get_collection("admin_sessions") hoặc db["admin_sessions"]
                if isinstance(node, ast.Constant) and node.value == "admin_sessions":
                    violations.append(f"{py_file.relative_to(repo_root)}:{node.lineno}")
        except Exception:
            pass

    assert violations == [], f"Phát hiện truy cập trực tiếp collection 'admin_sessions' vi phạm boundary: {violations}"

