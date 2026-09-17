"""Registered-operation gateway required by the LTX Rule (LTX-RULE-1).

Application code supplies a named operation, pinned version/checksum and bounded
domain parameters. Only a registered handler receives guarded collection access.
GuardedCollectionWrapper strictly enforces mutation policies, resource limits,
maxTimeMS timeouts, and prevents raw Mongo primitive or binary leakage.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import logging
import re
import time
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Literal, Mapping, Optional, Type, Union

import pymongo
from pydantic import BaseModel, ConfigDict, ValidationError

from backend.app.repositories.mongo_repository import MongoRepository

logger = logging.getLogger("huit_chatbot.operation_gateway")

OperationType = Literal["read", "command", "transaction"]
MutationPolicy = Literal["none", "insert_only", "update_only", "upsert", "delete_only", "any_mutation"]
AuditPolicy = Literal["always", "mutations_and_failures", "failures_only", "never"]
AuditFailPolicy = Literal["fail_open", "fail_closed"]


class OperationContractError(RuntimeError):
    """Public-safe failure raised when an LTX operation contract is violated."""


def is_transaction_supported(client: Any = None) -> bool:
    """Determine whether the current MongoDB deployment supports multi-document transactions."""
    if client is None:
        try:
            client = MongoRepository.get_client()
        except Exception:
            return False
    if not hasattr(client, "start_session"):
        return False
    topology = getattr(client, "topology_description", None)
    if topology is not None and hasattr(topology, "server_descriptions"):
        try:
            from pymongo.topology_description import TOPOLOGY_TYPE
            single_type = getattr(TOPOLOGY_TYPE, "Single", 1)
            if topology.topology_type == single_type or getattr(topology, "topology_type_name", "") == "Single":
                for server in topology.server_descriptions().values():
                    if getattr(server, "server_type_name", "") == "Standalone":
                        return False
        except Exception:
            pass
    return True


def _get_timeout_context(seconds: float):
    """Obtain PyMongo CSOT timeout context manager compatible with installed PyMongo version."""
    if seconds <= 0:
        return nullcontext()
    if hasattr(pymongo, "timeout"):
        try:
            return pymongo.timeout(seconds)
        except Exception as exc:
            logger.warning("Không thể khởi tạo pymongo.timeout(%.3fs): %s", seconds, exc)
            return nullcontext()
    return nullcontext()


def _is_mongo_timeout(exc: Exception) -> bool:
    """Check if exception represents a client-side or server-side MongoDB timeout."""
    if getattr(exc, "timeout", False) is True:
        return True
    exc_type = type(exc).__name__
    if exc_type in (
        "ExecutionTimeout",
        "NetworkTimeout",
        "WTimeoutError",
        "MaxTimeMSExpired",
        "ServerSelectionTimeoutError",
    ):
        return True
    if getattr(exc, "code", None) == 50:
        return True
    return False


@dataclass(frozen=True)
class OperationSpec:
    key: str
    version: str
    operation_type: OperationType
    parameter_model: Type[BaseModel]
    allowed_collections: tuple[str, ...]
    handler: Callable[["GuardedMongoContext", BaseModel], Any] = field(compare=False, repr=False)
    output_model: Optional[Type[BaseModel]] = None
    mutation_policy: MutationPolicy = "none"
    max_results: int = 100
    max_output_bytes: int = 256_000
    max_parameter_bytes: int = 64_000
    max_time_ms: int = 3_000
    audit_policy: AuditPolicy = "always"
    audit_fail_policy: AuditFailPolicy = "fail_open"
    declarative_query: Optional[Dict[str, Any]] = None
    declared_checksum: str = ""

    def _compute_handler_digest(self) -> str:
        try:
            src = inspect.getsource(self.handler)
            normalized = "\n".join(line.strip() for line in src.splitlines() if line.strip())
            return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        except Exception:
            co = getattr(self.handler, "__code__", None)
            if co:
                raw = f"{getattr(self.handler, '__qualname__', '')}:{co.co_code.hex()}:{co.co_consts}"
                return hashlib.sha256(raw.encode("utf-8")).hexdigest()
            return hashlib.sha256(str(self.handler).encode("utf-8")).hexdigest()

    @property
    def checksum(self) -> str:
        if self.version.startswith("1.") and not self.output_model:
            # Legacy v1 contract calculation to preserve compatibility
            contract = {
                "key": self.key,
                "version": self.version,
                "operation_type": self.operation_type,
                "parameters": self.parameter_model.model_json_schema(),
                "allowed_collections": list(self.allowed_collections),
                "max_results": self.max_results,
                "max_output_bytes": self.max_output_bytes,
                "max_time_ms": self.max_time_ms,
            }
        else:
            # Full LTX-RULE-1 v2+ contract calculation
            output_schema = {}
            if self.output_model is not None:
                if hasattr(self.output_model, "model_json_schema"):
                    output_schema = self.output_model.model_json_schema()
                else:
                    from pydantic import TypeAdapter
                    output_schema = TypeAdapter(self.output_model).json_schema()
            contract = {
                "key": self.key,
                "version": self.version,
                "operation_type": self.operation_type,
                "parameters": self.parameter_model.model_json_schema(),
                "output": output_schema,
                "allowed_collections": sorted(list(self.allowed_collections)),
                "mutation_policy": self.mutation_policy,
                "audit_policy": self.audit_policy,
                "audit_fail_policy": self.audit_fail_policy,
                "max_results": self.max_results,
                "max_output_bytes": self.max_output_bytes,
                "max_parameter_bytes": self.max_parameter_bytes,
                "max_time_ms": self.max_time_ms,
                "declarative_query": self.declarative_query or {},
                "handler_digest": self._compute_handler_digest(),
            }
        raw = json.dumps(contract, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class GuardedCollectionWrapper:
    """Guarded PyMongo collection wrapper that strictly enforces:
    - Allowed mutation policy (blocks forbidden inserts, updates, deletes).
    - Query timeout limits (max_time_ms / maxTimeMS) applied directly to Mongo commands.
    - Automatic session propagation when executing in a transactional session.
    - Limits and sanitized access.
    """
    def __init__(self, collection: Any, spec: OperationSpec, session: Optional[Any] = None):
        self._coll = collection
        self._spec = spec
        self._session = session

    def _inject_session(self, kwargs: dict) -> None:
        if self._session is not None and "session" not in kwargs:
            kwargs["session"] = self._session

    def _check_mutation(self, method_name: str, is_upsert: bool = False) -> None:
        policy = self._spec.mutation_policy
        if self._spec.operation_type == "read" or policy == "none":
            raise OperationContractError(
                f"Thao tác '{method_name}' bị từ chối: Operation {self._spec.key}@{self._spec.version} "
                f"chỉ có quyền 'read' với mutation_policy='{policy}'"
            )
        if policy == "insert_only" and method_name not in ("insert_one", "insert_many"):
            raise OperationContractError(
                f"Thao tác '{method_name}' bị từ chối bởi mutation_policy='insert_only' trên {self._spec.key}"
            )
        if policy == "update_only":
            if is_upsert or method_name not in ("update_one", "update_many", "find_one_and_update"):
                raise OperationContractError(
                    f"Thao tác '{method_name}' bị từ chối bởi mutation_policy='update_only' trên {self._spec.key}"
                )
        if policy == "delete_only" and method_name not in ("delete_one", "delete_many"):
            raise OperationContractError(
                f"Thao tác '{method_name}' bị từ chối bởi mutation_policy='delete_only' trên {self._spec.key}"
            )
        if policy == "upsert" and method_name in ("delete_one", "delete_many"):
            raise OperationContractError(
                f"Thao tác xóa '{method_name}' bị từ chối bởi mutation_policy='upsert' trên {self._spec.key}"
            )

    def find(self, *args, **kwargs):
        self._inject_session(kwargs)
        cursor = self._coll.find(*args, **kwargs)
        if hasattr(cursor, "max_time_ms"):
            try:
                cursor = cursor.max_time_ms(self._spec.max_time_ms)
            except Exception as exc:
                logger.warning("Không thể áp dụng max_time_ms trên cursor find: %s", exc)
        return cursor

    def find_one(self, *args, **kwargs):
        self._inject_session(kwargs)
        try:
            if "max_time_ms" not in kwargs:
                kwargs["max_time_ms"] = self._spec.max_time_ms
            return self._coll.find_one(*args, **kwargs)
        except TypeError as exc:
            logger.warning("find_one không hỗ trợ tham số max_time_ms (%s), thử lại không có tham số", exc)
            kwargs.pop("max_time_ms", None)
            return self._coll.find_one(*args, **kwargs)

    def aggregate(self, pipeline, *args, **kwargs):
        self._inject_session(kwargs)
        try:
            if "maxTimeMS" not in kwargs:
                kwargs["maxTimeMS"] = self._spec.max_time_ms
            return self._coll.aggregate(pipeline, *args, **kwargs)
        except TypeError as exc:
            logger.warning("aggregate không hỗ trợ tham số maxTimeMS (%s), thử lại không có tham số", exc)
            kwargs.pop("maxTimeMS", None)
            return self._coll.aggregate(pipeline, *args, **kwargs)

    def count_documents(self, filter, *args, **kwargs):
        self._inject_session(kwargs)
        try:
            if "maxTimeMS" not in kwargs:
                kwargs["maxTimeMS"] = self._spec.max_time_ms
            return self._coll.count_documents(filter, *args, **kwargs)
        except TypeError as exc:
            logger.warning("count_documents không hỗ trợ tham số maxTimeMS (%s), thử lại không có tham số", exc)
            kwargs.pop("maxTimeMS", None)
            return self._coll.count_documents(filter, *args, **kwargs)

    def estimated_document_count(self, *args, **kwargs):
        self._inject_session(kwargs)
        try:
            if "maxTimeMS" not in kwargs:
                kwargs["maxTimeMS"] = self._spec.max_time_ms
            return self._coll.estimated_document_count(*args, **kwargs)
        except TypeError as exc:
            logger.warning("estimated_document_count không hỗ trợ tham số maxTimeMS (%s), thử lại không có tham số", exc)
            kwargs.pop("maxTimeMS", None)
            return self._coll.estimated_document_count(*args, **kwargs)

    def insert_one(self, document, *args, **kwargs):
        self._check_mutation("insert_one")
        self._inject_session(kwargs)
        return self._coll.insert_one(document, *args, **kwargs)

    def insert_many(self, documents, *args, **kwargs):
        self._check_mutation("insert_many")
        self._inject_session(kwargs)
        return self._coll.insert_many(documents, *args, **kwargs)

    def update_one(self, filter, update, *args, **kwargs):
        is_upsert = kwargs.get("upsert", False)
        self._check_mutation("update_one", is_upsert=is_upsert)
        self._inject_session(kwargs)
        return self._coll.update_one(filter, update, *args, **kwargs)

    def update_many(self, filter, update, *args, **kwargs):
        is_upsert = kwargs.get("upsert", False)
        self._check_mutation("update_many", is_upsert=is_upsert)
        self._inject_session(kwargs)
        return self._coll.update_many(filter, update, *args, **kwargs)

    def replace_one(self, filter, replacement, *args, **kwargs):
        is_upsert = kwargs.get("upsert", False)
        self._check_mutation("replace_one", is_upsert=is_upsert)
        self._inject_session(kwargs)
        return self._coll.replace_one(filter, replacement, *args, **kwargs)

    def delete_one(self, filter, *args, **kwargs):
        self._check_mutation("delete_one")
        self._inject_session(kwargs)
        return self._coll.delete_one(filter, *args, **kwargs)

    def delete_many(self, filter, *args, **kwargs):
        self._check_mutation("delete_many")
        self._inject_session(kwargs)
        return self._coll.delete_many(filter, *args, **kwargs)

    def find_one_and_update(self, filter, update, *args, **kwargs):
        is_upsert = kwargs.get("upsert", False)
        self._check_mutation("find_one_and_update", is_upsert=is_upsert)
        self._inject_session(kwargs)
        try:
            if "maxTimeMS" not in kwargs:
                kwargs["maxTimeMS"] = self._spec.max_time_ms
            return self._coll.find_one_and_update(filter, update, *args, **kwargs)
        except TypeError as exc:
            logger.warning("find_one_and_update không hỗ trợ tham số maxTimeMS (%s), thử lại không có tham số", exc)
            kwargs.pop("maxTimeMS", None)
            return self._coll.find_one_and_update(filter, update, *args, **kwargs)

    def find_one_and_delete(self, filter, *args, **kwargs):
        self._check_mutation("find_one_and_delete")
        self._inject_session(kwargs)
        try:
            if "maxTimeMS" not in kwargs:
                kwargs["maxTimeMS"] = self._spec.max_time_ms
            return self._coll.find_one_and_delete(filter, *args, **kwargs)
        except TypeError as exc:
            logger.warning("find_one_and_delete không hỗ trợ tham số maxTimeMS (%s), thử lại không có tham số", exc)
            kwargs.pop("maxTimeMS", None)
            return self._coll.find_one_and_delete(filter, *args, **kwargs)


class GuardedMongoContext:
    def __init__(self, spec: OperationSpec, session: Optional[Any] = None):
        self._spec = spec
        self._session = session

    def collection(self, name: str) -> GuardedCollectionWrapper:
        if name not in self._spec.allowed_collections:
            raise OperationContractError(
                f"Operation {self._spec.key}@{self._spec.version} không được truy cập collection {name}"
            )
        raw_coll = MongoRepository.get_collection(name)
        return GuardedCollectionWrapper(raw_coll, self._spec, session=self._session)

    @property
    def session(self) -> Optional[Any]:
        return self._session

    def ping(self) -> None:
        MongoRepository.get_client().admin.command("ping")

    @property
    def database_name(self) -> str:
        return MongoRepository.get_db().name


_REGISTRY: Dict[tuple[str, str], OperationSpec] = {}


def _check_nested_models_extra_forbid(model_cls: Any, visited: Optional[set] = None) -> None:
    if visited is None:
        visited = set()
    from typing import get_args, get_origin, Union
    import types
    if not isinstance(model_cls, type):
        origin = get_origin(model_cls)
        if origin in (Union, types.UnionType):
            for a in get_args(model_cls):
                if a is not type(None):
                    _check_nested_models_extra_forbid(a, visited)
            return
        return
    if not issubclass(model_cls, BaseModel):
        return
    if model_cls in visited:
        return
    visited.add(model_cls)

    if getattr(model_cls, "model_config", {}).get("extra") != "forbid":
        raise OperationContractError(
            f"Model '{model_cls.__name__}' bắt buộc phải có extra='forbid'"
        )

    for field_name, field_info in model_cls.model_fields.items():
        ann = field_info.annotation
        types_to_check = [ann]
        origin = get_origin(ann)
        if origin is not None:
            types_to_check.extend(get_args(ann))
        for t in types_to_check:
            _check_nested_models_extra_forbid(t, visited)


def register_operation(spec: OperationSpec) -> OperationSpec:
    identity = (spec.key, spec.version)
    if identity in _REGISTRY:
        raise RuntimeError(f"Operation đã đăng ký: {spec.key}@{spec.version}")

    # Validation requirements for LTX-RULE-1
    if not spec.version.startswith("1.") or spec.output_model is not None:
        if getattr(spec.parameter_model, "model_config", {}).get("extra") != "forbid":
            raise OperationContractError(
                f"Parameter model của operation {spec.key}@{spec.version} bắt buộc phải có extra='forbid'"
            )
        if spec.output_model is None:
            raise OperationContractError(
                f"Operation {spec.key}@{spec.version} bắt buộc phải khai báo output_model"
            )
        output_model = spec.output_model
        from typing import get_origin, get_args, Union
        import types
        if get_origin(output_model) in (Union, types.UnionType):
            inner_models = [a for a in get_args(output_model) if a is not type(None)]
            for im in inner_models:
                if getattr(im, "model_config", {}).get("extra") != "forbid":
                    raise OperationContractError(
                        f"Output model của operation {spec.key}@{spec.version} bắt buộc phải có extra='forbid'"
                    )
        else:
            if getattr(output_model, "model_config", {}).get("extra") != "forbid":
                raise OperationContractError(
                    f"Output model của operation {spec.key}@{spec.version} bắt buộc phải có extra='forbid'"
                )
        if spec.operation_type == "read" and spec.mutation_policy != "none":
            raise OperationContractError(
                f"Read operation {spec.key}@{spec.version} bắt buộc phải có mutation_policy='none'"
            )

        # Enforce all nested models inside parameter and output have extra='forbid'
        _check_nested_models_extra_forbid(spec.parameter_model)
        if spec.output_model is not None:
            _check_nested_models_extra_forbid(spec.output_model)

    if spec.operation_type != "read" and spec.mutation_policy != "none":
        if spec.audit_policy == "never":
            allowed_never = {"jobs.heartbeat", "jobs.release_lease"}
            if spec.key not in allowed_never:
                raise OperationContractError(
                    f"Command nghiệp vụ '{spec.key}@{spec.version}' bắt buộc phải audit 'always' hoặc 'mutations_and_failures', không được dùng 'never'."
                )

    if spec.audit_fail_policy == "fail_closed" and spec.operation_type != "read" and spec.mutation_policy != "none":
        # If MongoDB client is active and cannot guarantee transactions, refuse registration
        if MongoRepository._client is not None and not is_transaction_supported(MongoRepository._client):
            raise OperationContractError(
                f"Không thể đăng ký operation mutation '{spec.key}@{spec.version}' với audit_fail_policy='fail_closed': "
                f"Deployment MongoDB hiện tại là Standalone, không bảo đảm được tính nguyên tử của multi-document transactions."
            )

    if spec.declared_checksum and spec.declared_checksum != spec.checksum:
        raise RuntimeError(
            f"Checksum không khớp cho operation {spec.key}@{spec.version}: "
            f"declared={spec.declared_checksum} vs computed={spec.checksum}"
        )
    _REGISTRY[identity] = spec
    return spec


def get_operation(key: str, version: str) -> OperationSpec:
    try:
        return _REGISTRY[(key, version)]
    except KeyError as exc:
        raise OperationContractError(f"Operation không tồn tại: {key}@{version}") from exc


def _result_count(result: Any) -> int:
    if isinstance(result, list):
        return len(result)
    return 1 if result is not None else 0


def _sanitize_and_check_payload(obj: Any, path: str = "", context: str = "kết quả") -> Any:
    """Recursively inspect payload, block raw binary / large base64 / raw ObjectId, and strip raw MongoDB _id."""
    if isinstance(obj, (bytes, bytearray, memoryview)):
        raise OperationContractError(f"Phát hiện raw binary không được phép trong {context} tại '{path or 'root'}'")
    if type(obj).__name__ == "ObjectId" or (hasattr(obj, "__class__") and obj.__class__.__name__ == "ObjectId"):
        raise OperationContractError(f"Phát hiện raw ObjectId không được phép trong {context} tại '{path or 'root'}'")
    if isinstance(obj, str):
        if len(obj) > 400 and ("data:image/" in obj or ";base64," in obj):
            raise OperationContractError(f"Phát hiện Data URI Base64 không được phép trong {context} tại '{path or 'root'}'")
        if len(obj) > 10000 and re.match(r"^[A-Za-z0-9+/=]{10000,}$", obj):
            raise OperationContractError(f"Phát hiện raw Base64 lớn không được phép trong {context} tại '{path or 'root'}'")
        return obj
    if isinstance(obj, dict):
        cleaned = {}
        for k, v in obj.items():
            if k == "_id":
                continue  # Never leak raw _id through gateway
            sub_path = f"{path}.{k}" if path else k
            cleaned[k] = _sanitize_and_check_payload(v, sub_path, context=context)
        return cleaned
    if isinstance(obj, (list, tuple)):
        return [_sanitize_and_check_payload(item, f"{path}[{idx}]", context=context) for idx, item in enumerate(obj)]
    return obj


def _should_audit(spec: OperationSpec, status: str) -> bool:
    policy = spec.audit_policy
    if policy == "never":
        return False
    if policy == "always":
        return True
    if policy == "failures_only":
        return status == "failed"
    if policy == "mutations_and_failures":
        return spec.operation_type != "read" or status == "failed"
    return True


def _write_audit(
    spec: OperationSpec,
    *,
    principal_id: str,
    request_id: str,
    status: str,
    duration_ms: float,
    output_bytes: int,
    parameter_hash: str,
    error_type: Optional[str] = None,
    session: Optional[Any] = None,
) -> None:
    if not _should_audit(spec, status):
        return

    # Strictly log only bounded metadata, SHA-256 parameter hash and class name in error_type.
    # Never log user prompts, credentials, tokens, or raw payload content.
    audit_doc = {
        "schema_version": 1,
        "operation_key": spec.key,
        "operation_version": spec.version,
        "operation_checksum": spec.checksum,
        "operation_type": spec.operation_type,
        "mutation_policy": spec.mutation_policy,
        "principal_id": principal_id,
        "request_id": request_id,
        "status": status,
        "duration_ms": round(duration_ms, 2),
        "output_bytes": output_bytes,
        "parameter_hash": parameter_hash,
        "error_type": error_type,
        "created_at": datetime.now(timezone.utc),
    }

    try:
        kwargs = {}
        if session is not None:
            kwargs["session"] = session
        MongoRepository.get_collection("operation_audit").insert_one(audit_doc, **kwargs)
    except Exception as exc:
        logger.warning("Không thể ghi operation audit cho %s@%s: %s", spec.key, spec.version, type(exc).__name__)
        if spec.audit_fail_policy == "fail_closed":
            raise OperationContractError(
                f"Thao tác '{spec.key}@{spec.version}' bị hủy do lỗi ghi nhận kiểm toán (audit log failure)"
            ) from exc


def _validate_output(spec: OperationSpec, sanitized: Any, key: str, version: str) -> Any:
    """Validate and serialize handler output against declared Pydantic output model."""
    if spec.output_model is None:
        return sanitized

    if sanitized is None:
        is_nullable = False
        if getattr(spec.output_model, "__nullable__", False) or getattr(spec.output_model, "nullable", False) is True:
            is_nullable = True
        else:
            try:
                from pydantic import TypeAdapter
                TypeAdapter(spec.output_model).validate_python(None)
                is_nullable = True
            except Exception:
                try:
                    spec.output_model.model_validate(None)
                    is_nullable = True
                except Exception:
                    is_nullable = False

        if is_nullable:
            return None
        else:
            raise OperationContractError(
                f"Dữ liệu trả về không thỏa mãn output schema của {key}@{version}: None không được phép (non-nullable)"
            )

    try:
        if isinstance(sanitized, list):
            try:
                validated = spec.output_model.model_validate(sanitized)
                return validated.model_dump(mode="json")
            except Exception:
                return [
                    spec.output_model.model_validate(item).model_dump(mode="json")
                    for item in sanitized
                ]
        elif isinstance(sanitized, dict):
            if hasattr(spec.output_model, "model_validate"):
                validated = spec.output_model.model_validate(sanitized)
                return validated.model_dump(mode="json")
            else:
                from pydantic import TypeAdapter
                validated = TypeAdapter(spec.output_model).validate_python(sanitized)
                if hasattr(validated, "model_dump"):
                    return validated.model_dump(mode="json")
                return validated
        else:
            if hasattr(spec.output_model, "model_validate"):
                validated = spec.output_model.model_validate(sanitized)
            else:
                from pydantic import TypeAdapter
                validated = TypeAdapter(spec.output_model).validate_python(sanitized)
            if isinstance(validated, BaseModel):
                return validated.model_dump(mode="json")
            return getattr(validated, "root", validated)
    except ValidationError as v_err:
        raise OperationContractError(
            f"Dữ liệu trả về không thỏa mãn output schema của {key}@{version}: {v_err.errors()}"
        ) from v_err


def execute_registered_operation(
    *,
    key: str,
    version: str,
    checksum: str,
    parameters: Mapping[str, Any],
    principal_id: str = "system",
    request_id: str = "internal",
) -> Any:
    spec = get_operation(key, version)
    if checksum != spec.checksum:
        raise OperationContractError(f"Authority checksum không khớp cho {key}@{version}")

    try:
        params = spec.parameter_model.model_validate(dict(parameters))
    except ValidationError as exc:
        try:
            _sanitize_and_check_payload(dict(parameters), context="tham số input")
        except OperationContractError:
            raise
        raise OperationContractError(f"Tham số operation không hợp lệ: {key}@{version}") from exc

    # Sanitize input parameters after Pydantic validation but before handler
    _sanitize_and_check_payload(dict(parameters), context="tham số input")
    _sanitize_and_check_payload(params.model_dump(mode="python"), context="tham số input")

    parameter_json = json.dumps(params.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    param_bytes = len(parameter_json.encode("utf-8"))
    if param_bytes > spec.max_parameter_bytes:
        raise OperationContractError(
            f"Tham số operation vượt parameter budget ({param_bytes}B > {spec.max_parameter_bytes}B): {key}@{version}"
        )
    parameter_hash = hashlib.sha256(parameter_json.encode("utf-8")).hexdigest()
    started = time.perf_counter()
    status = "failed"
    output_bytes = 0
    error_type: Optional[str] = None

    is_mutation = spec.operation_type != "read" and spec.mutation_policy != "none"
    use_transaction = (spec.audit_fail_policy == "fail_closed" and is_mutation)

    if use_transaction:
        client = MongoRepository.get_client()
        if not is_transaction_supported(client):
            raise OperationContractError(
                f"Không thể thực thi {key}@{version} với audit_fail_policy='fail_closed': "
                f"Deployment MongoDB không bảo đảm transactions (yêu cầu Replica Set hoặc Mongos) để đảm bảo tính nguyên tử."
            )

        session = client.start_session()
        try:
            with session.start_transaction():
                guarded_ctx = GuardedMongoContext(spec, session=session)
                timeout_sec = spec.max_time_ms / 1000.0
                with _get_timeout_context(timeout_sec):
                    raw_result = spec.handler(guarded_ctx, params)

                duration_ms = (time.perf_counter() - started) * 1000
                if duration_ms > spec.max_time_ms:
                    raise OperationContractError(
                        f"Operation vượt time budget ({duration_ms:.1f}ms > {spec.max_time_ms}ms): {key}@{version}"
                    )

                if _result_count(raw_result) > spec.max_results:
                    raise OperationContractError(f"Operation vượt result limit: {key}@{version}")

                sanitized = _sanitize_and_check_payload(raw_result)
                final_result = _validate_output(spec, sanitized, key, version)

                output_bytes = len(json.dumps(final_result, default=str, ensure_ascii=False).encode("utf-8"))
                if output_bytes > spec.max_output_bytes:
                    raise OperationContractError(
                        f"Operation vượt output budget ({output_bytes}B > {spec.max_output_bytes}B): {key}@{version}"
                    )

                # Atomic audit write inside transaction
                _write_audit(
                    spec,
                    principal_id=principal_id,
                    request_id=request_id,
                    status="success",
                    duration_ms=duration_ms,
                    output_bytes=output_bytes,
                    parameter_hash=parameter_hash,
                    error_type=None,
                    session=session,
                )
                # Successful exit from with session.start_transaction() commits the transaction!
            return final_result
        except Exception as exc:
            error_type = type(exc).__name__
            if not (isinstance(exc, OperationContractError) and "audit log failure" in str(exc)):
                try:
                    _write_audit(
                        spec,
                        principal_id=principal_id,
                        request_id=request_id,
                        status="failed",
                        duration_ms=(time.perf_counter() - started) * 1000,
                        output_bytes=0,
                        parameter_hash=parameter_hash,
                        error_type=error_type,
                        session=None,
                    )
                except Exception:
                    pass
            if isinstance(exc, OperationContractError):
                raise
            if _is_mongo_timeout(exc):
                raise OperationContractError(f"Operation vượt timeout ({spec.max_time_ms}ms): {key}@{version}") from exc
            raise
        finally:
            session.end_session()
    else:
        try:
            guarded_ctx = GuardedMongoContext(spec)
            timeout_sec = spec.max_time_ms / 1000.0
            with _get_timeout_context(timeout_sec):
                raw_result = spec.handler(guarded_ctx, params)

            duration_ms = (time.perf_counter() - started) * 1000
            if duration_ms > spec.max_time_ms:
                raise OperationContractError(
                    f"Operation vượt time budget ({duration_ms:.1f}ms > {spec.max_time_ms}ms): {key}@{version}"
                )

            if _result_count(raw_result) > spec.max_results:
                raise OperationContractError(f"Operation vượt result limit: {key}@{version}")

            sanitized = _sanitize_and_check_payload(raw_result)
            final_result = _validate_output(spec, sanitized, key, version)

            output_bytes = len(json.dumps(final_result, default=str, ensure_ascii=False).encode("utf-8"))
            if output_bytes > spec.max_output_bytes:
                raise OperationContractError(
                    f"Operation vượt output budget ({output_bytes}B > {spec.max_output_bytes}B): {key}@{version}"
                )

            status = "success"
            return final_result
        except Exception as exc:
            error_type = type(exc).__name__
            if isinstance(exc, OperationContractError):
                raise
            if _is_mongo_timeout(exc):
                raise OperationContractError(f"Operation vượt timeout ({spec.max_time_ms}ms): {key}@{version}") from exc
            raise
        finally:
            _write_audit(
                spec,
                principal_id=principal_id,
                request_id=request_id,
                status=status,
                duration_ms=(time.perf_counter() - started) * 1000,
                output_bytes=output_bytes,
                parameter_hash=parameter_hash,
                error_type=error_type,
                session=None,
            )

