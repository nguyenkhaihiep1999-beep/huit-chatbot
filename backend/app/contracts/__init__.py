"""Canonical JSON Schema registry used by backend, frontend, and MongoDB."""

from .schema_registry import (
    SCHEMA_ROOT,
    SchemaRegistryError,
    iter_schema_entries,
    load_schema,
    schema_sha256,
)

__all__ = [
    "SCHEMA_ROOT",
    "SchemaRegistryError",
    "iter_schema_entries",
    "load_schema",
    "schema_sha256",
]
