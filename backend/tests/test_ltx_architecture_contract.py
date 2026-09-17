"""Release-blocking dependency and authority checks for LTX-RULE-1."""
import importlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = ROOT / "backend" / "app"
EXCEPTION_FILE = ROOT / "docs" / "architecture" / "ltx_exceptions.json"
RAW_ACCESS = re.compile(
    r"get_(?:kb|events|artifacts)?_?collection\s*\(|"
    r"\.\s*(?:find_one|aggregate|insert_one|update_one|update_many|"
    r"delete_one|delete_many|count_documents|estimated_document_count)\s*\("
)


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _raw_access_files():
    found = set()
    for path in APP_ROOT.rglob("*.py"):
        relative = _relative(path)
        if relative.startswith("backend/app/data_access/"):
            continue
        if relative.startswith("backend/app/repositories/"):
            continue
        if RAW_ACCESS.search(path.read_text(encoding="utf-8")):
            found.add(relative)
    return found


def test_routes_cannot_access_mongo_primitives():
    violations = []
    for path in (APP_ROOT / "api" / "routes").rglob("*.py"):
        if RAW_ACCESS.search(path.read_text(encoding="utf-8")):
            violations.append(_relative(path))
    assert not violations, f"Routes bypass LTX operations: {violations}"


def test_raw_data_access_matches_exact_exception_registry():
    registry = json.loads(EXCEPTION_FILE.read_text(encoding="utf-8"))
    exceptions = registry.get("exceptions", [])
    declared = {item["path"] for item in exceptions}
    assert len(declared) == len(exceptions), "Duplicate LTX exception paths"
    assert all(item.get("owner") and item.get("reason") and item.get("expires_by") for item in exceptions)
    assert _raw_access_files() == declared


def test_operation_specs_live_only_in_registered_operation_modules():
    violations = []
    for path in APP_ROOT.rglob("*.py"):
        relative = _relative(path)
        if "OperationSpec(" not in path.read_text(encoding="utf-8"):
            continue
        if relative == "backend/app/data_access/operation_gateway.py":
            continue
        if not relative.startswith("backend/app/data_access/registered_operations/"):
            violations.append(relative)
    assert not violations, f"Unregistered operation specs: {violations}"


def test_domain_adapters_do_not_receive_raw_mongo_access():
    violations = []
    operation_root = APP_ROOT / "data_access" / "operations"
    for path in operation_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if RAW_ACCESS.search(source) or "MongoRepository" in source:
            violations.append(_relative(path))
    assert not violations, f"Domain adapters bypass gateway: {violations}"


def test_registered_operation_checksums_are_declared_and_valid():
    modules = (
        "backend.app.data_access.registered_operations.admission_visuals_v1",
        "backend.app.data_access.registered_operations.generated_images_v1",
        "backend.app.data_access.registered_operations.system_observability_v1",
        "backend.app.data_access.registered_operations.admission_visuals_v2",
        "backend.app.data_access.registered_operations.generated_images_v2",
        "backend.app.data_access.registered_operations.system_observability_v2",
        "backend.app.data_access.registered_operations.rag_operations_v2",
        "backend.app.data_access.registered_operations.cache_operations_v2",
        "backend.app.data_access.registered_operations.telemetry_operations_v2",
        "backend.app.data_access.registered_operations.asset_operations_v2",
        "backend.app.data_access.registered_operations.job_operations_v2",
    )
    for name in modules:
        importlib.import_module(name)
    from backend.app.data_access.operation_gateway import _REGISTRY

    assert _REGISTRY
    for spec in _REGISTRY.values():
        assert spec.declared_checksum, f"Missing declared checksum: {spec.key}@{spec.version}"
        assert spec.declared_checksum == spec.checksum
