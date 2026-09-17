# LTX Rule implementation

LTX-RULE-1 is a release-blocking architecture contract for the chatbot.

## Frontend dependency direction

Runtime UI follows this direction:

`component -> domain hook -> feature API -> shared HTTP client`

- Components render state and invoke domain actions. They do not contain endpoint strings or import feature API modules.
- Hooks coordinate React state. They do not call `fetch` or the shared transport directly.
- Feature API modules own endpoint paths and wire-format conversion.
- `frontend/src/shared/api/httpClient.ts` is the only production source file allowed to call `fetch`.
- Session credentials live in `frontend/src/shared/auth/csrfStore.ts`; session bootstrap is owned by the session feature.

`frontend/tests/architectureContract.test.ts` enforces these rules without a browser driver.

## Backend dependency direction

New and migrated flows follow:

`route -> service/use case -> domain operation adapter -> registered operation -> guarded Mongo context`

Registered operations are stored only under
`backend/app/data_access/registered_operations`. Each operation declares:

- stable key and semantic version;
- Pydantic parameter contract with `extra="forbid"` (no loose `Any` or `Dict[str, Any]` permitted at Registered Operation boundaries);
- collection allowlist;
- result, output-size, parameter bounds and execution-time budgets;
- input parameter sanitization rejecting raw bytes, raw ObjectIds, Data URIs, and oversized payloads;
- strict BSON Date / datetime formatting on new write operations (string dates forbidden on v2 writes);
- a checksum pinned both at registration and at the domain adapter boundary.

The gateway validates authority and parameters, restricts collection access and
writes structured audit records to `operation_audit`. Routes, services, RAG pipeline,
cache and telemetry never receive a raw Mongo collection, filter or pipeline.

All functional domains (admission visuals, generated-image metadata, administrator
metrics, system health/readiness, RAG knowledge base retrieval, semantic cache, durable
job queue, asset deduplication, and telemetry audit events) have been fully migrated to
50 Registered Operations v2 with strict checksum pinning and max_time_ms enforcement.

## Admin Portal & Security Policy
- Administrative access is guarded via server-issued HttpOnly session cookies (`huit_admin_token`, `huit_session_id`) and CSRF tokens (`X-CSRF-Token`).
- ZERO admin tokens or credentials are permitted in `localStorage` or `sessionStorage`.
- Audit tables strictly sanitize data: raw prompts, user queries, full stack traces, and API keys are stripped before view rendering.

## NDJSON Streaming Protocol v2 Canonical Events
- Canonical events are strictly defined: `start`, `token`, `progress`, `artifact`, `error`, `done`, `cancelled`.
- No redundant, duplicate, or ambiguous event types are permitted.
- Sequence numbers are strictly monotonic (1..N). Disconnects and resumes rely on sequence markers with zero LLM re-invocation.

## Change procedure

Changing a registered operation contract requires a new operation version and a
new pinned checksum. Do not silently edit a released operation. Data-shape changes
must use a dry-run-first migration with a backup and post-migration verification.

Run the release gates with:

```text
pytest backend/tests/test_ltx_architecture_contract.py
pytest backend/tests/test_streaming_protocol_v2.py
npm test -- --run tests/architectureContract.test.ts
npm test -- --run tests/adminWorkflow.test.tsx
```
