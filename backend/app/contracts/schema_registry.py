"""Read and verify the human-reviewed JSON Schema registry.

Git files under ``backend/json_schemas`` are authoritative. MongoDB receives a
versioned, checksummed backup through migration 022; runtime code never mutates
the registry silently.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable


SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "json_schemas"
REGISTRY_FILE = SCHEMA_ROOT / "registry.json"
SUPPORTED_KINDS = {"api", "stream", "mongodb"}


class SchemaRegistryError(RuntimeError):
    """Raised when the canonical registry is missing, unsafe, or inconsistent."""


@lru_cache(maxsize=1)
def _manifest() -> Dict[str, Any]:
    try:
        raw = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SchemaRegistryError("Cannot load canonical JSON Schema registry") from exc
    if raw.get("registry_version") != 1 or not isinstance(raw.get("contracts"), list):
        raise SchemaRegistryError("Unsupported or malformed JSON Schema registry manifest")
    return raw


def _safe_schema_path(relative_file: str) -> Path:
    candidate = (SCHEMA_ROOT / relative_file).resolve()
    root = SCHEMA_ROOT.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise SchemaRegistryError(f"Schema path escapes registry root: {relative_file}") from exc
    if candidate.suffix.lower() != ".json" or not candidate.is_file():
        raise SchemaRegistryError(f"Schema file is missing or invalid: {relative_file}")
    return candidate


def iter_schema_entries(*, frontend_only: bool = False) -> Iterable[Dict[str, Any]]:
    seen = set()
    for item in _manifest()["contracts"]:
        if not isinstance(item, dict):
            raise SchemaRegistryError("Every registry contract must be an object")
        required = {"schema_id", "version", "kind", "file", "frontend", "consumers"}
        if not required.issubset(item):
            raise SchemaRegistryError(f"Registry entry is missing fields: {sorted(required - set(item))}")
        key = (item["schema_id"], item["version"])
        if key in seen:
            raise SchemaRegistryError(f"Duplicate schema identity: {key}")
        seen.add(key)
        if item["kind"] not in SUPPORTED_KINDS:
            raise SchemaRegistryError(f"Unsupported schema kind: {item['kind']}")
        if not isinstance(item["consumers"], list) or not item["consumers"]:
            raise SchemaRegistryError(f"Schema has no declared consumers: {item['schema_id']}")
        _safe_schema_path(item["file"])
        if frontend_only and not item["frontend"]:
            continue
        yield deepcopy(item)


@lru_cache(maxsize=32)
def _load_schema_cached(schema_id: str, version: str) -> Dict[str, Any]:
    matches = [
        entry
        for entry in iter_schema_entries()
        if entry["schema_id"] == schema_id and entry["version"] == version
    ]
    if len(matches) != 1:
        raise SchemaRegistryError(f"Unknown canonical schema: {schema_id}@{version}")
    path = _safe_schema_path(matches[0]["file"])
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SchemaRegistryError(f"Cannot parse canonical schema: {schema_id}@{version}") from exc
    if not isinstance(document, dict):
        raise SchemaRegistryError(f"Canonical schema must be an object: {schema_id}@{version}")
    if matches[0]["kind"] == "mongodb":
        if "$jsonSchema" not in document:
            raise SchemaRegistryError(f"MongoDB schema lacks $jsonSchema: {schema_id}@{version}")
    elif document.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise SchemaRegistryError(f"API/stream schema is not draft 2020-12: {schema_id}@{version}")
    return document


def load_schema(schema_id: str, version: str) -> Dict[str, Any]:
    """Return a defensive copy so callers cannot mutate the cached contract."""
    return deepcopy(_load_schema_cached(schema_id, version))


def schema_sha256(schema_id: str, version: str) -> str:
    """Hash semantic JSON independent of whitespace or key order."""
    canonical = json.dumps(
        _load_schema_cached(schema_id, version),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
