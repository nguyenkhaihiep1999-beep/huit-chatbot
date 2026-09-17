"""Unit and integration test suite for the Registered Operation Gateway (LTX-RULE-1).

Tests enforce:
1. Checksum mismatch rejection
2. Handler and declarative query modification invalidates checksum
3. Extra parameter rejection (strict parameter model with extra='forbid')
4. Invalid output schema rejection
5. Collection access outside allowlist rejection
6. Resource budgets (result count, output bytes, execution time) enforcement
7. Raw binary and large Base64 leakage prevention and raw _id stripping
8. Mutation policy enforcement (read-only forbids writes, insert_only forbids updates/deletes)
9. Duplicate key/version registration rejection
10. Audit policy and audit fail policy (fail_open vs fail_closed)
"""
import time
from typing import List, Optional
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel, ConfigDict, Field

from backend.app.data_access.operation_gateway import (
    GuardedCollectionWrapper,
    GuardedMongoContext,
    OperationContractError,
    OperationSpec,
    execute_registered_operation,
    get_operation,
    register_operation,
)


class DummyParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query_text: str = Field(min_length=1, max_length=100)
    limit: int = Field(default=10, ge=1, le=50)


class DummyOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    count: int


# ==============================================================================
# 1. CHECKSUM MISMATCH
# ==============================================================================
def test_checksum_mismatch_rejected():
    def _dummy_handler(ctx, params):
        return {"status": "ok", "count": 1}

    spec = OperationSpec(
        key="test.checksum_mismatch",
        version="2.0.0",
        operation_type="read",
        parameter_model=DummyParams,
        output_model=DummyOutput,
        allowed_collections=("test_coll",),
        mutation_policy="none",
        handler=_dummy_handler,
        declared_checksum="",
    )
    correct_checksum = spec.checksum
    spec_with_checksum = OperationSpec(
        key=spec.key,
        version=spec.version,
        operation_type=spec.operation_type,
        parameter_model=spec.parameter_model,
        output_model=spec.output_model,
        allowed_collections=spec.allowed_collections,
        mutation_policy=spec.mutation_policy,
        handler=spec.handler,
        declared_checksum=correct_checksum,
    )
    register_operation(spec_with_checksum)

    # Calling with tampered checksum must be rejected
    with pytest.raises(OperationContractError, match="Authority checksum không khớp"):
        execute_registered_operation(
            key="test.checksum_mismatch",
            version="2.0.0",
            checksum="0000000000000000000000000000000000000000000000000000000000000000",
            parameters={"query_text": "hello", "limit": 5},
        )


# ==============================================================================
# 2. HANDLER OR QUERY CHANGE INVALIDATES CHECKSUM
# ==============================================================================
def test_handler_or_query_change_invalidates_checksum():
    def _handler_v1(ctx, params):
        return {"status": "v1", "count": 1}

    def _handler_v2(ctx, params):
        # Different implementation
        return {"status": "v2", "count": 2}

    spec_v1 = OperationSpec(
        key="test.handler_change",
        version="2.0.0",
        operation_type="read",
        parameter_model=DummyParams,
        output_model=DummyOutput,
        allowed_collections=("test_coll",),
        handler=_handler_v1,
        declared_checksum="",
    )

    spec_v2 = OperationSpec(
        key="test.handler_change",
        version="2.0.0",
        operation_type="read",
        parameter_model=DummyParams,
        output_model=DummyOutput,
        allowed_collections=("test_coll",),
        handler=_handler_v2,
        declared_checksum="",
    )

    assert spec_v1.checksum != spec_v2.checksum, "Changing handler must change checksum"

    # Changing declarative query must also change checksum
    spec_query_1 = OperationSpec(
        key="test.query_change",
        version="2.0.0",
        operation_type="read",
        parameter_model=DummyParams,
        output_model=DummyOutput,
        allowed_collections=("test_coll",),
        handler=_handler_v1,
        declarative_query={"status": "active"},
        declared_checksum="",
    )
    spec_query_2 = OperationSpec(
        key="test.query_change",
        version="2.0.0",
        operation_type="read",
        parameter_model=DummyParams,
        output_model=DummyOutput,
        allowed_collections=("test_coll",),
        handler=_handler_v1,
        declarative_query={"status": "archived"},
        declared_checksum="",
    )
    assert spec_query_1.checksum != spec_query_2.checksum, "Changing query must change checksum"

    # Registering with stale checksum must fail
    with pytest.raises(RuntimeError, match="Checksum không khớp"):
        register_operation(OperationSpec(
            key="test.handler_change_stale",
            version="2.0.0",
            operation_type="read",
            parameter_model=DummyParams,
            output_model=DummyOutput,
            allowed_collections=("test_coll",),
            handler=_handler_v2,
            declared_checksum=spec_v1.checksum,
        ))


# ==============================================================================
# 3. EXTRA PARAMETER REJECTED
# ==============================================================================
def test_extra_parameter_rejected():
    def _handler(ctx, params):
        return {"status": "ok", "count": params.limit}

    spec = OperationSpec(
        key="test.extra_param",
        version="2.0.0",
        operation_type="read",
        parameter_model=DummyParams,
        output_model=DummyOutput,
        allowed_collections=("test_coll",),
        handler=_handler,
        declared_checksum="",
    )
    spec = register_operation(OperationSpec(**{**spec.__dict__, "declared_checksum": spec.checksum}))

    # Pass unexpected injection parameter
    with pytest.raises(OperationContractError, match="Tham số operation không hợp lệ"):
        execute_registered_operation(
            key=spec.key,
            version=spec.version,
            checksum=spec.checksum,
            parameters={"query_text": "valid", "limit": 10, "unauthorized_sql_injection": "DROP TABLE"},
        )


# ==============================================================================
# 4. INVALID OUTPUT SCHEMA REJECTED
# ==============================================================================
def test_invalid_output_rejected():
    def _bad_output_handler(ctx, params):
        # Returns wrong types or missing required fields
        return {"status": "ok", "count": "not_an_integer"}

    spec = OperationSpec(
        key="test.bad_output",
        version="2.0.0",
        operation_type="read",
        parameter_model=DummyParams,
        output_model=DummyOutput,
        allowed_collections=("test_coll",),
        handler=_bad_output_handler,
        declared_checksum="",
    )
    spec = register_operation(OperationSpec(**{**spec.__dict__, "declared_checksum": spec.checksum}))

    with pytest.raises(OperationContractError, match="output schema"):
        execute_registered_operation(
            key=spec.key,
            version=spec.version,
            checksum=spec.checksum,
            parameters={"query_text": "valid", "limit": 5},
        )


# ==============================================================================
# 5. COLLECTION OUTSIDE ALLOWLIST REJECTED
# ==============================================================================
def test_disallowed_collection_rejected():
    def _trespassing_handler(ctx, params):
        # Attempts to read private users collection
        return ctx.collection("secret_credentials").find_one({})

    spec = OperationSpec(
        key="test.disallowed_collection",
        version="2.0.0",
        operation_type="read",
        parameter_model=DummyParams,
        output_model=DummyOutput,
        allowed_collections=("public_kb",),
        handler=_trespassing_handler,
        declared_checksum="",
    )
    spec = register_operation(OperationSpec(**{**spec.__dict__, "declared_checksum": spec.checksum}))

    with pytest.raises(OperationContractError, match="không được truy cập collection secret_credentials"):
        execute_registered_operation(
            key=spec.key,
            version=spec.version,
            checksum=spec.checksum,
            parameters={"query_text": "valid", "limit": 5},
        )


# ==============================================================================
# 6. RESOURCE BUDGETS ENFORCED
# ==============================================================================
def test_resource_budgets_enforced():
    # 6a. Result count budget
    def _overflow_results_handler(ctx, params):
        return [{"status": "ok", "count": i} for i in range(10)]

    spec_results = OperationSpec(
        key="test.overflow_results",
        version="2.0.0",
        operation_type="read",
        parameter_model=DummyParams,
        output_model=DummyOutput,
        allowed_collections=("test_coll",),
        max_results=3,
        handler=_overflow_results_handler,
        declared_checksum="",
    )
    spec_results = register_operation(OperationSpec(**{**spec_results.__dict__, "declared_checksum": spec_results.checksum}))

    with pytest.raises(OperationContractError, match="vượt result limit"):
        execute_registered_operation(
            key=spec_results.key,
            version=spec_results.version,
            checksum=spec_results.checksum,
            parameters={"query_text": "valid", "limit": 5},
        )

    # 6b. Output byte budget
    def _overflow_bytes_handler(ctx, params):
        return {"status": "x" * 5000, "count": 1}

    class LargeOutput(BaseModel):
        model_config = ConfigDict(extra="forbid")
        status: str
        count: int

    spec_bytes = OperationSpec(
        key="test.overflow_bytes",
        version="2.0.0",
        operation_type="read",
        parameter_model=DummyParams,
        output_model=LargeOutput,
        allowed_collections=("test_coll",),
        max_output_bytes=500,
        handler=_overflow_bytes_handler,
        declared_checksum="",
    )
    spec_bytes = register_operation(OperationSpec(**{**spec_bytes.__dict__, "declared_checksum": spec_bytes.checksum}))

    with pytest.raises(OperationContractError, match="vượt output budget"):
        execute_registered_operation(
            key=spec_bytes.key,
            version=spec_bytes.version,
            checksum=spec_bytes.checksum,
            parameters={"query_text": "valid", "limit": 5},
        )

    # 6c. Execution time budget
    def _slow_handler(ctx, params):
        time.sleep(0.06)
        return {"status": "ok", "count": 1}

    spec_time = OperationSpec(
        key="test.slow_handler",
        version="2.0.0",
        operation_type="read",
        parameter_model=DummyParams,
        output_model=DummyOutput,
        allowed_collections=("test_coll",),
        max_time_ms=30,
        handler=_slow_handler,
        declared_checksum="",
    )
    spec_time = register_operation(OperationSpec(**{**spec_time.__dict__, "declared_checksum": spec_time.checksum}))

    with pytest.raises(OperationContractError, match="vượt time budget"):
        execute_registered_operation(
            key=spec_time.key,
            version=spec_time.version,
            checksum=spec_time.checksum,
            parameters={"query_text": "valid", "limit": 5},
        )


# ==============================================================================
# 7. RAW BINARY & LARGE BASE64 BLOCKED, _id STRIPPED
# ==============================================================================
def test_raw_binary_and_base64_blocked():
    # 7a. Raw bytes blocked
    def _binary_handler(ctx, params):
        return {"status": "ok", "count": 1, "raw_data": b"\x00\x01\x02"}

    spec_bin = OperationSpec(
        key="test.binary_blocked",
        version="2.0.0",
        operation_type="read",
        parameter_model=DummyParams,
        output_model=DummyOutput,
        allowed_collections=("test_coll",),
        handler=_binary_handler,
        declared_checksum="",
    )
    spec_bin = register_operation(OperationSpec(**{**spec_bin.__dict__, "declared_checksum": spec_bin.checksum}))

    with pytest.raises(OperationContractError, match="Phát hiện raw binary"):
        execute_registered_operation(
            key=spec_bin.key,
            version=spec_bin.version,
            checksum=spec_bin.checksum,
            parameters={"query_text": "valid", "limit": 5},
        )

    # 7b. Data URI Base64 blocked
    def _base64_handler(ctx, params):
        return {"status": "data:image/png;base64," + "A" * 500, "count": 1}

    spec_b64 = OperationSpec(
        key="test.base64_blocked",
        version="2.0.0",
        operation_type="read",
        parameter_model=DummyParams,
        output_model=DummyOutput,
        allowed_collections=("test_coll",),
        handler=_base64_handler,
        declared_checksum="",
    )
    spec_b64 = register_operation(OperationSpec(**{**spec_b64.__dict__, "declared_checksum": spec_b64.checksum}))

    with pytest.raises(OperationContractError, match="Phát hiện Data URI Base64"):
        execute_registered_operation(
            key=spec_b64.key,
            version=spec_b64.version,
            checksum=spec_b64.checksum,
            parameters={"query_text": "valid", "limit": 5},
        )

    # 7c. _id is stripped
    def _id_leak_handler(ctx, params):
        return {"_id": "raw_mongo_object_id_12345", "status": "ok", "count": 1}

    spec_id = OperationSpec(
        key="test.id_stripped",
        version="2.0.0",
        operation_type="read",
        parameter_model=DummyParams,
        output_model=DummyOutput,
        allowed_collections=("test_coll",),
        handler=_id_leak_handler,
        declared_checksum="",
    )
    spec_id = register_operation(OperationSpec(**{**spec_id.__dict__, "declared_checksum": spec_id.checksum}))

    result = execute_registered_operation(
        key=spec_id.key,
        version=spec_id.version,
        checksum=spec_id.checksum,
        parameters={"query_text": "valid", "limit": 5},
    )
    assert "_id" not in result, "_id must be completely stripped from output"
    assert result == {"status": "ok", "count": 1}


# ==============================================================================
# 8. MUTATION POLICY ENFORCEMENT
# ==============================================================================
def test_mutation_policy_enforcement():
    # 8a. Read operation cannot perform insert, update, or delete
    def _illegal_write_handler(ctx, params):
        ctx.collection("test_coll").insert_one({"name": "forbidden"})
        return {"status": "ok", "count": 1}

    spec_read = OperationSpec(
        key="test.illegal_write",
        version="2.0.0",
        operation_type="read",
        parameter_model=DummyParams,
        output_model=DummyOutput,
        allowed_collections=("test_coll",),
        mutation_policy="none",
        handler=_illegal_write_handler,
        declared_checksum="",
    )
    spec_read = register_operation(OperationSpec(**{**spec_read.__dict__, "declared_checksum": spec_read.checksum}))

    with patch("backend.app.repositories.mongo_repository.MongoRepository.get_collection") as mock_get:
        mock_get.return_value = MagicMock()
        with pytest.raises(OperationContractError, match="chỉ có quyền 'read' với mutation_policy='none'"):
            execute_registered_operation(
                key=spec_read.key,
                version=spec_read.version,
                checksum=spec_read.checksum,
                parameters={"query_text": "valid", "limit": 5},
            )

    # 8b. insert_only cannot perform updates or deletes
    def _illegal_update_handler(ctx, params):
        ctx.collection("test_coll").update_one({"name": "target"}, {"$set": {"name": "modified"}})
        return {"status": "ok", "count": 1}

    spec_insert_only = OperationSpec(
        key="test.illegal_update",
        version="2.0.0",
        operation_type="command",
        parameter_model=DummyParams,
        output_model=DummyOutput,
        allowed_collections=("test_coll",),
        mutation_policy="insert_only",
        handler=_illegal_update_handler,
        declared_checksum="",
    )
    spec_insert_only = register_operation(OperationSpec(**{**spec_insert_only.__dict__, "declared_checksum": spec_insert_only.checksum}))

    with patch("backend.app.repositories.mongo_repository.MongoRepository.get_collection") as mock_get:
        mock_get.return_value = MagicMock()
        with pytest.raises(OperationContractError, match="mutation_policy='insert_only'"):
            execute_registered_operation(
                key=spec_insert_only.key,
                version=spec_insert_only.version,
                checksum=spec_insert_only.checksum,
                parameters={"query_text": "valid", "limit": 5},
            )


# ==============================================================================
# 9. DUPLICATE REGISTRATION REJECTED
# ==============================================================================
def test_duplicate_registration_rejected():
    def _dummy(ctx, params):
        return {"status": "ok", "count": 1}

    spec = OperationSpec(
        key="test.duplicate_key",
        version="2.0.0",
        operation_type="read",
        parameter_model=DummyParams,
        output_model=DummyOutput,
        allowed_collections=("test_coll",),
        handler=_dummy,
        declared_checksum="",
    )
    register_operation(OperationSpec(**{**spec.__dict__, "declared_checksum": spec.checksum}))

    # Attempting to register exact same identity
    with pytest.raises(RuntimeError, match="Operation đã đăng ký"):
        register_operation(OperationSpec(**{**spec.__dict__, "declared_checksum": spec.checksum}))


# ==============================================================================
# 10. AUDIT POLICY AND FAIL POLICY
# ==============================================================================
def test_audit_policy_and_fail_policy():
    # 10a. failures_only policy
    def _success_handler(ctx, params):
        return {"status": "ok", "count": 1}

    spec_audit_failures = OperationSpec(
        key="test.audit_failures_only",
        version="2.0.0",
        operation_type="read",
        parameter_model=DummyParams,
        output_model=DummyOutput,
        allowed_collections=("test_coll",),
        audit_policy="failures_only",
        handler=_success_handler,
        declared_checksum="",
    )
    spec_audit_failures = register_operation(OperationSpec(**{**spec_audit_failures.__dict__, "declared_checksum": spec_audit_failures.checksum}))

    with patch("backend.app.repositories.mongo_repository.MongoRepository.get_collection") as mock_coll:
        mock_audit = MagicMock()
        mock_coll.return_value = mock_audit

        execute_registered_operation(
            key=spec_audit_failures.key,
            version=spec_audit_failures.version,
            checksum=spec_audit_failures.checksum,
            parameters={"query_text": "valid", "limit": 5},
        )
        # Audit should not be inserted on success when policy is failures_only
        mock_audit.insert_one.assert_not_called()

    # 10b. audit_fail_policy='fail_closed' cancels command if audit write fails
    def _command_handler(ctx, params):
        return {"status": "ok", "count": 1}

    spec_fail_closed = OperationSpec(
        key="test.audit_fail_closed",
        version="2.0.0",
        operation_type="command",
        parameter_model=DummyParams,
        output_model=DummyOutput,
        allowed_collections=("test_coll",),
        mutation_policy="any_mutation",
        audit_policy="always",
        audit_fail_policy="fail_closed",
        handler=_command_handler,
        declared_checksum="",
    )
    spec_fail_closed = register_operation(OperationSpec(**{**spec_fail_closed.__dict__, "declared_checksum": spec_fail_closed.checksum}))

    with patch("backend.app.repositories.mongo_repository.MongoRepository.get_collection") as mock_coll:
        mock_audit = MagicMock()
        mock_audit.insert_one.side_effect = ConnectionError("Mongo disk full")
        mock_coll.return_value = mock_audit

        with pytest.raises(OperationContractError, match="audit log failure"):
            execute_registered_operation(
                key=spec_fail_closed.key,
                version=spec_fail_closed.version,
                checksum=spec_fail_closed.checksum,
                parameters={"query_text": "valid", "limit": 5},
            )


# ==============================================================================
# 11. STRICT OUTPUT CONTRACT & NULLABLE TESTS
# ==============================================================================
def test_none_output_rejected_for_non_nullable_schema():
    """None bị từ chối với schema không nullable."""
    def _none_handler(ctx, params):
        return None

    spec = OperationSpec(
        key="test.none_rejected_strict",
        version="2.0.0",
        operation_type="read",
        parameter_model=DummyParams,
        output_model=DummyOutput,
        allowed_collections=("test_coll",),
        handler=_none_handler,
        declared_checksum="",
    )
    spec = register_operation(OperationSpec(**{**spec.__dict__, "declared_checksum": spec.checksum}))

    with pytest.raises(OperationContractError, match="None không được phép"):
        execute_registered_operation(
            key=spec.key,
            version=spec.version,
            checksum=spec.checksum,
            parameters={"query_text": "test", "limit": 5},
        )


def test_none_output_accepted_for_nullable_schema():
    """None được chấp nhận với schema nullable."""
    class NullableDummyOutput(BaseModel):
        model_config = ConfigDict(extra="forbid")
        __nullable__ = True
        status: str
        count: int

    def _none_handler(ctx, params):
        return None

    spec = OperationSpec(
        key="test.none_accepted_nullable",
        version="2.0.0",
        operation_type="read",
        parameter_model=DummyParams,
        output_model=NullableDummyOutput,
        allowed_collections=("test_coll",),
        handler=_none_handler,
        declared_checksum="",
    )
    spec = register_operation(OperationSpec(**{**spec.__dict__, "declared_checksum": spec.checksum}))

    res = execute_registered_operation(
        key=spec.key,
        version=spec.version,
        checksum=spec.checksum,
        parameters={"query_text": "test", "limit": 5},
    )
    assert res is None


class NestedItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tag: str
    code: int


class NestedContainerOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    detail: NestedItem


def test_nested_object_extra_fields_rejected():
    """Field thừa trong object lồng nhau bị từ chối (extra='forbid')."""
    def _handler_with_extra(ctx, params):
        return {
            "title": "Document A",
            "detail": {
                "tag": "alpha",
                "code": 100,
                "unauthorized_nested_field": "exploit_attempt"
            }
        }

    spec = OperationSpec(
        key="test.nested_extra_forbid",
        version="2.0.0",
        operation_type="read",
        parameter_model=DummyParams,
        output_model=NestedContainerOutput,
        allowed_collections=("test_coll",),
        handler=_handler_with_extra,
        declared_checksum="",
    )
    spec = register_operation(OperationSpec(**{**spec.__dict__, "declared_checksum": spec.checksum}))

    with pytest.raises(OperationContractError, match="output schema"):
        execute_registered_operation(
            key=spec.key,
            version=spec.version,
            checksum=spec.checksum,
            parameters={"query_text": "test", "limit": 5},
        )


def test_valid_nested_object_serializes_correctly():
    """Object hợp lệ vẫn serialize đúng."""
    def _valid_handler(ctx, params):
        return {
            "title": "Document A",
            "detail": {
                "tag": "alpha",
                "code": 100
            }
        }

    spec = OperationSpec(
        key="test.nested_valid_serialize",
        version="2.0.0",
        operation_type="read",
        parameter_model=DummyParams,
        output_model=NestedContainerOutput,
        allowed_collections=("test_coll",),
        handler=_valid_handler,
        declared_checksum="",
    )
    spec = register_operation(OperationSpec(**{**spec.__dict__, "declared_checksum": spec.checksum}))

    res = execute_registered_operation(
        key=spec.key,
        version=spec.version,
        checksum=spec.checksum,
        parameters={"query_text": "test", "limit": 5},
    )
    assert res == {
        "title": "Document A",
        "detail": {
            "tag": "alpha",
            "code": 100
        }
    }


def test_binary_objectid_and_base64_blocked():
    """Binary, ObjectId và Base64 vẫn bị chặn."""
    class FakeObjectId:
        pass
    FakeObjectId.__name__ = "ObjectId"

    def _objectid_handler(ctx, params):
        return {"status": "ok", "count": 1, "custom_ref": FakeObjectId()}

    spec_oid = OperationSpec(
        key="test.objectid_blocked",
        version="2.0.0",
        operation_type="read",
        parameter_model=DummyParams,
        output_model=DummyOutput,
        allowed_collections=("test_coll",),
        handler=_objectid_handler,
        declared_checksum="",
    )
    spec_oid = register_operation(OperationSpec(**{**spec_oid.__dict__, "declared_checksum": spec_oid.checksum}))

    with pytest.raises(OperationContractError, match="Phát hiện raw ObjectId"):
        execute_registered_operation(
            key=spec_oid.key,
            version=spec_oid.version,
            checksum=spec_oid.checksum,
            parameters={"query_text": "test", "limit": 5},
        )

    def _bin_handler(ctx, params):
        return {"status": "ok", "count": 1, "payload": b"\x00\xff"}

    spec_bin = OperationSpec(
        key="test.raw_binary_blocked_explicit",
        version="2.0.0",
        operation_type="read",
        parameter_model=DummyParams,
        output_model=DummyOutput,
        allowed_collections=("test_coll",),
        handler=_bin_handler,
        declared_checksum="",
    )
    spec_bin = register_operation(OperationSpec(**{**spec_bin.__dict__, "declared_checksum": spec_bin.checksum}))

    with pytest.raises(OperationContractError, match="Phát hiện raw binary"):
        execute_registered_operation(
            key=spec_bin.key,
            version=spec_bin.version,
            checksum=spec_bin.checksum,
            parameters={"query_text": "test", "limit": 5},
        )

    def _b64_handler(ctx, params):
        return {"status": "ok", "count": 1, "payload": "A" * 10500}

    spec_b64 = OperationSpec(
        key="test.raw_base64_blocked_explicit",
        version="2.0.0",
        operation_type="read",
        parameter_model=DummyParams,
        output_model=DummyOutput,
        allowed_collections=("test_coll",),
        handler=_b64_handler,
        declared_checksum="",
    )
    spec_b64 = register_operation(OperationSpec(**{**spec_b64.__dict__, "declared_checksum": spec_b64.checksum}))

    with pytest.raises(OperationContractError, match="Phát hiện raw Base64 lớn"):
        execute_registered_operation(
            key=spec_b64.key,
            version=spec_b64.version,
            checksum=spec_b64.checksum,
            parameters={"query_text": "test", "limit": 5},
        )


# ==============================================================================
# 16. INPUT SANITIZATION BLOCKS BINARY AND BASE64
# ==============================================================================
def test_input_sanitization_blocks_binary_and_base64():
    """Chặn bytes, Data URI và Base64 lớn ở đầu vào tham số trước handler."""
    def _echo_handler(ctx, params):
        return {"status": "ok", "count": len(params.query_text)}

    spec = OperationSpec(
        key="test.input_sanitization",
        version="2.0.0",
        operation_type="read",
        parameter_model=DummyParams,
        output_model=DummyOutput,
        allowed_collections=("test_coll",),
        handler=_echo_handler,
        declared_checksum="",
    )
    spec = register_operation(OperationSpec(**{**spec.__dict__, "declared_checksum": spec.checksum}))

    # 1. Raw binary in input parameter
    with pytest.raises(OperationContractError, match="Phát hiện raw binary"):
        execute_registered_operation(
            key=spec.key,
            version=spec.version,
            checksum=spec.checksum,
            parameters={"query_text": b"\x00\x01\x02", "limit": 5},
        )

    # 2. Data URI Base64 in input parameter
    data_uri = "data:image/png;base64," + "A" * 500
    with pytest.raises(OperationContractError, match="Phát hiện Data URI Base64"):
        execute_registered_operation(
            key=spec.key,
            version=spec.version,
            checksum=spec.checksum,
            parameters={"query_text": data_uri, "limit": 5},
        )

    # 3. Raw large Base64 in input parameter
    class LongParams(BaseModel):
        model_config = ConfigDict(extra="forbid")
        payload: str

    spec_long = OperationSpec(
        key="test.input_large_b64",
        version="2.0.0",
        operation_type="read",
        parameter_model=LongParams,
        output_model=DummyOutput,
        allowed_collections=("test_coll",),
        max_parameter_bytes=128_000,
        handler=lambda ctx, p: {"status": "ok", "count": 1},
        declared_checksum="",
    )
    spec_long = register_operation(OperationSpec(**{**spec_long.__dict__, "declared_checksum": spec_long.checksum}))

    with pytest.raises(OperationContractError, match="Phát hiện raw Base64 lớn"):
        execute_registered_operation(
            key=spec_long.key,
            version=spec_long.version,
            checksum=spec_long.checksum,
            parameters={"payload": "A" * 10500},
        )


# ==============================================================================
# 17. NESTED EXTRA FIELD REJECTED
# ==============================================================================
def test_input_nested_extra_field_rejected():
    """Extra fields inside nested models are strictly forbidden."""
    class NestedChild(BaseModel):
        model_config = ConfigDict(extra="forbid")
        code: int

    class NestedParent(BaseModel):
        model_config = ConfigDict(extra="forbid")
        name: str
        child: NestedChild

    spec = OperationSpec(
        key="test.nested_extra_rejected",
        version="2.0.0",
        operation_type="read",
        parameter_model=NestedParent,
        output_model=DummyOutput,
        allowed_collections=("test_coll",),
        handler=lambda ctx, p: {"status": "ok", "count": p.child.code},
        declared_checksum="",
    )
    spec = register_operation(OperationSpec(**{**spec.__dict__, "declared_checksum": spec.checksum}))

    # Extra field in nested child must be rejected
    with pytest.raises(OperationContractError, match="Tham số operation không hợp lệ"):
        execute_registered_operation(
            key=spec.key,
            version=spec.version,
            checksum=spec.checksum,
            parameters={
                "name": "parent",
                "child": {
                    "code": 42,
                    "malicious_extra": "injected",
                },
            },
        )

    # Valid nested input succeeds
    res = execute_registered_operation(
        key=spec.key,
        version=spec.version,
        checksum=spec.checksum,
        parameters={"name": "parent", "child": {"code": 42}},
    )
    assert res["count"] == 42

    # Registering an operation with a nested model that allows extra must be rejected at registration
    class BadChild(BaseModel):
        model_config = ConfigDict(extra="allow")
        code: int

    class BadParent(BaseModel):
        model_config = ConfigDict(extra="forbid")
        child: BadChild

    with pytest.raises(OperationContractError, match="bắt buộc phải có extra='forbid'"):
        register_operation(
            OperationSpec(
                key="test.bad_nested_allowed",
                version="2.0.0",
                operation_type="read",
                parameter_model=BadParent,
                output_model=DummyOutput,
                allowed_collections=("test_coll",),
                handler=lambda ctx, p: {"status": "ok", "count": 1},
                declared_checksum="",
            )
        )


# ==============================================================================
# 18. CREATED_AT STRING REJECTED AT WRITE V2
# ==============================================================================
def test_write_v2_rejects_string_created_at():
    """Write operations in v2 reject string created_at; must be datetime (BSON Date)."""
    from pydantic import ValidationError
    from backend.app.data_access.registered_operations.admission_visuals_v2 import SaveAdmissionVisualParams
    from backend.app.data_access.registered_operations.generated_images_v2 import InsertGeneratedImageParams
    from backend.app.data_access.registered_operations.job_operations_v2 import CreateJobParams

    # 1. admission_visual save
    with pytest.raises(ValidationError, match="created_at phải là datetime"):
        SaveAdmissionVisualParams.model_validate({
            "visual_id": "vis_123",
            "document": {
                "visual_id": "vis_123",
                "title": "IT Admission",
                "created_at": "2026-09-16T12:00:00Z",
            },
        })

    # 2. generated_image insert
    with pytest.raises(ValidationError, match="created_at phải là datetime"):
        InsertGeneratedImageParams.model_validate({
            "document": {
                "image_id": "a" * 24,
                "content_hash": "b" * 64,
                "created_at": "2026-09-16T12:00:00Z",
            },
        })

    # 3. jobs create
    with pytest.raises(ValidationError, match="created_at phải là đối tượng datetime"):
        CreateJobParams.model_validate({
            "job": {
                "job_id": "job_12345678",
                "action": "export",
                "created_at": "2026-09-16T12:00:00Z",
            },
        })


# ==============================================================================
# 19. TRANSACTION ROLLBACK WHEN AUDIT FAILS (FAIL_CLOSED)
# ==============================================================================
def test_transaction_rollback_when_audit_fails_fail_closed():
    """When audit_fail_policy='fail_closed', audit failure aborts transaction and rolls back mutation."""
    from backend.app.repositories.mongo_repository import MongoRepository

    inserted_docs = []

    def _mutation_handler(ctx, params):
        col = ctx.collection("test_coll")
        col.insert_one({"record_id": params.query_text})
        inserted_docs.append(params.query_text)
        return {"status": "created", "count": 1}

    spec = OperationSpec(
        key="test.tx_fail_closed",
        version="2.0.0",
        operation_type="command",
        mutation_policy="insert_only",
        parameter_model=DummyParams,
        output_model=DummyOutput,
        allowed_collections=("test_coll",),
        audit_policy="always",
        audit_fail_policy="fail_closed",
        handler=_mutation_handler,
        declared_checksum="",
    )
    spec = register_operation(OperationSpec(**{**spec.__dict__, "declared_checksum": spec.checksum}))

    mock_client = MagicMock()
    mock_session = MagicMock()
    mock_tx_context = MagicMock()
    mock_session.start_transaction.return_value = mock_tx_context
    mock_client.start_session.return_value = mock_session
    mock_client.topology_description.topology_type = 2  # ReplicaSet

    mock_test_col = MagicMock()
    mock_audit_col = MagicMock()
    mock_audit_col.insert_one.side_effect = RuntimeError("Audit database disk failure")

    def _mock_get_coll(name):
        if name == "operation_audit":
            return mock_audit_col
        return mock_test_col

    with patch.object(MongoRepository, "get_client", return_value=mock_client), \
         patch.object(MongoRepository, "get_collection", side_effect=_mock_get_coll):

        with pytest.raises(OperationContractError, match="bị hủy do lỗi ghi nhận kiểm toán"):
            execute_registered_operation(
                key=spec.key,
                version=spec.version,
                checksum=spec.checksum,
                parameters={"query_text": "doc_1", "limit": 1},
            )

        # Verify transaction context __enter__ and __exit__ were called with error (triggering rollback)
        mock_session.start_transaction.assert_called_once()
        mock_tx_context.__exit__.assert_called_once()
        exc_args = mock_tx_context.__exit__.call_args[0]
        assert exc_args[0] is not None, "Transaction context must exit with exception to trigger abort/rollback"
        mock_session.end_session.assert_called_once()


# ==============================================================================
# 20. STANDALONE MONGO REJECTS FAIL_CLOSED MUTATIONS
# ==============================================================================
def test_standalone_mongo_rejects_fail_closed_mutations():
    """Standalone MongoDB cannot support multi-document transactions and must reject fail_closed mutations."""
    from backend.app.repositories.mongo_repository import MongoRepository
    from pymongo.topology_description import TOPOLOGY_TYPE

    spec = OperationSpec(
        key="test.standalone_reject",
        version="2.0.0",
        operation_type="command",
        mutation_policy="insert_only",
        parameter_model=DummyParams,
        output_model=DummyOutput,
        allowed_collections=("test_coll",),
        audit_policy="always",
        audit_fail_policy="fail_closed",
        handler=lambda ctx, p: {"status": "ok", "count": 1},
        declared_checksum="",
    )
    spec = register_operation(OperationSpec(**{**spec.__dict__, "declared_checksum": spec.checksum}))

    mock_client = MagicMock()
    mock_server = MagicMock()
    mock_server.server_type_name = "Standalone"
    mock_client.topology_description.topology_type = getattr(TOPOLOGY_TYPE, "Single", 1)
    mock_client.topology_description.server_descriptions.return_value = {"localhost:27017": mock_server}

    with patch.object(MongoRepository, "get_client", return_value=mock_client):
        with pytest.raises(OperationContractError, match="Deployment MongoDB không bảo đảm transactions"):
            execute_registered_operation(
                key=spec.key,
                version=spec.version,
                checksum=spec.checksum,
                parameters={"query_text": "test", "limit": 1},
            )


# ==============================================================================
# 21. FAIL_OPEN CONTINUES WHEN AUDIT FAILS
# ==============================================================================
def test_fail_open_continues_when_audit_fails():
    """When audit_fail_policy='fail_open', audit failure logs a warning but operation succeeds."""
    from backend.app.repositories.mongo_repository import MongoRepository

    spec = OperationSpec(
        key="test.audit_fail_open_success",
        version="2.0.0",
        operation_type="command",
        mutation_policy="insert_only",
        parameter_model=DummyParams,
        output_model=DummyOutput,
        allowed_collections=("test_coll",),
        audit_policy="always",
        audit_fail_policy="fail_open",
        handler=lambda ctx, p: {"status": "created", "count": 10},
        declared_checksum="",
    )
    spec = register_operation(OperationSpec(**{**spec.__dict__, "declared_checksum": spec.checksum}))

    mock_audit_col = MagicMock()
    mock_audit_col.insert_one.side_effect = RuntimeError("Audit disk full")

    with patch.object(MongoRepository, "get_collection", return_value=mock_audit_col):
        res = execute_registered_operation(
            key=spec.key,
            version=spec.version,
            checksum=spec.checksum,
            parameters={"query_text": "test", "limit": 5},
        )
        assert res["status"] == "created"
        assert res["count"] == 10


# ==============================================================================
# 22. PARAMETER SIZE EXCEEDING BUDGET REJECTED
# ==============================================================================
def test_parameter_size_exceeding_budget_rejected():
    """Parameter JSON size exceeding max_parameter_bytes is rejected before handler execution."""
    spec = OperationSpec(
        key="test.param_budget_exceeded",
        version="2.0.0",
        operation_type="read",
        parameter_model=DummyParams,
        output_model=DummyOutput,
        allowed_collections=("test_coll",),
        max_parameter_bytes=60,  # Tight budget
        handler=lambda ctx, p: {"status": "ok", "count": 1},
        declared_checksum="",
    )
    spec = register_operation(OperationSpec(**{**spec.__dict__, "declared_checksum": spec.checksum}))

    # JSON of {"limit": 5, "query_text": "a" * 80} is > 100 bytes
    with pytest.raises(OperationContractError, match="vượt parameter budget"):
        execute_registered_operation(
            key=spec.key,
            version=spec.version,
            checksum=spec.checksum,
            parameters={"query_text": "a" * 80, "limit": 5},
        )

    # Small parameter within budget succeeds
    res = execute_registered_operation(
        key=spec.key,
        version=spec.version,
        checksum=spec.checksum,
        parameters={"query_text": "hi", "limit": 1},
    )
    assert res["status"] == "ok"

