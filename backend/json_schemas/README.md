# HUIT canonical JSON Schema registry

This directory is the human-reviewed source of truth for data that crosses a
system boundary. API models, MongoDB validators, frontend runtime validators,
hooks, and shared types are consumers of these contracts; they must not invent
their own incompatible shapes.

Rules:

1. Change a schema here first and bump its semantic version when compatibility
   changes.
2. Run `python scripts/sync_json_schemas.py` to refresh the frontend copies.
3. Run backend and frontend contract tests. A checksum or dependency violation
   blocks release.
4. Apply migration `022_backup_json_schema_registry.py` to copy the reviewed
   schemas and their SHA-256 checksums into MongoDB `schema_registry`.
5. MongoDB is a versioned backup/audit registry. Git remains the authoritative
   editable source; application startup never silently rewrites schemas.

The first protected contracts are session bootstrap, chat requests, NDJSON v2
stream events, and the LTX operation audit record.
