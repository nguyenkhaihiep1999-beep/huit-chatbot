# HUIT Canonical JSON Schema — Contract Core

This directory is the human-reviewed **Contract Core** and sole source of truth
for all data structures that cross system boundaries. API models, MongoDB validators,
queue/job payloads, frontend runtime validators, hooks, and presentation components
are downstream consumers of these contracts; they must not invent independent shapes.

## Architectural Dependency Hierarchy

```
Human-reviewed JSON Schema (`backend/json_schemas/`)
  │
  ├──► Backend Pydantic Schemas (`backend/app/api/schemas/`)
  │    └── MongoDB Validators & Models (`backend/app/models/mongo_models.py`)
  │
  └──► Frontend Generated Contracts (`frontend/src/shared/contracts/schemas/`)
         │
         ▼
       Runtime Validators & Type Guards (`frontend/src/shared/contracts/index.ts`)
         │
         ▼
       Feature API Client (`frontend/src/features/*/api/`)
         │
         ▼
       Feature Hook Implementation (`frontend/src/features/*/hooks/`)
         │
         ▼
       Public Hook Facade (`frontend/hooks/`)
         │
         ▼
       App & UI Components (`frontend/src/app/`, `frontend/src/features/*/components/`)
```

## Operational Rules

1. **Schema First**: Change a schema here first and bump its semantic version whenever
   compatibility or schema fields change.
2. **Synchronize Frontend**: Run `python scripts/sync_json_schemas.py` to compile and
   sync frontend schema copies into `frontend/src/shared/contracts/schemas/`.
3. **Verify Integrity**: Run backend and frontend contract tests:
   - `python -m pytest backend/tests/test_canonical_json_schema_registry.py`
   - `npm test` in `frontend/` (verifies checksums, manifest, and runtime validators).
4. **Audit & Backup**: Apply migration `022_backup_json_schema_registry.py` to persist
   reviewed schemas and their SHA-256 hashes into MongoDB `schema_registry`.
5. **Authoritative Git**: Git remains the authoritative editable source. MongoDB
   acts as an immutable audit registry. Application startup never silently rewrites contracts.

### Decision request v2

`huit.decision.decision-request@2.0.0` is the active JEV request contract.
Score questions require an ordered `criteria` array of 2–10 string descriptions
(at most 500 characters each). Choice/Noul retain optional object criteria.
The local contract intentionally supports plain-text rubric descriptions, not
all structured rubric variants accepted by TypeSafe.

The v1 schema is retained unchanged as a deprecated historical contract; it is
not the contract for new Score requests. Decision result remains at v1. The
provider checks matching answer types and validates Score legend/probability
keys against the request's level indices before normalizing the result.
These decision contracts are backend-only, so no frontend schema copy changes.

---

## Schema Coverage Matrix (Phase 5 Inventory)

All data crossing system boundaries (API public boundaries, JSON/NDJSON streaming, Queue/job payloads, MongoDB persistence, and Frontend runtime contracts) are strictly tracked in this canonical matrix. Classes internal to a single process are intentionally omitted from schema-ization.

| Boundary | Contract | Canonical Schema (`schema_id`) | Backend Validation | Frontend Validation | Mongo Validation | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **API** | Session Bootstrap Response | `huit.api.session-bootstrap-response` | `SessionResponse` (Pydantic) | `validateSessionResponse` (AJV) | N/A | Active |
| **API** | Chat Request | `huit.api.chat-request` | `ChatRequest` (Pydantic) | `chatApi.sendMessage` | N/A | Active |
| **API** | Error Response | `huit.api.error-response` | FastAPI Exception Handlers | `httpClient` error handler | N/A | Active |
| **API** | Artifact Manifest | `huit.api.artifact-manifest` | `ArtifactManifest` (Pydantic) | `artifactsApi` contracts | N/A | Active |
| **API** | Artifact Summary | `huit.api.artifact-summary` | `ArtifactSummary` (Pydantic) | `artifactsApi` contracts | N/A | Active |
| **API** | Artifact Plan Request | `huit.api.artifact-plan-request` | `ArtifactPlanRequest` (Pydantic) | `artifactsApi.createPlan` | N/A | Active |
| **API** | Artifact Render Request | `huit.api.artifact-render-request` | `ArtifactRenderRequest` (Pydantic) | `artifactsApi.render` | N/A | Active |
| **API** | Artifact Upscale Request | `huit.api.artifact-upscale-request` | `ArtifactUpscaleRequest` (Pydantic) | `artifactsApi.upscale` | N/A | Active |
| **API** | Artifact Export Request | `huit.api.artifact-export-request` | `ArtifactExportRequest` (Pydantic) | `artifactsApi.export` | N/A | Active |
| **API** | Job Status Response | `huit.api.job-status-response` | `JobStatusResponse` (Pydantic) | `artifactsApi.getJobStatus` | N/A | Active |
| **API** | Image Generation Request | `huit.api.image-create-request` | `ImageCreateRequest` (Pydantic) | `imageApi` contracts | N/A | Active |
| **API** | Image Generation Result | `huit.api.image-result` | `ImageResult` (Pydantic) | `imageApi` contracts | N/A | Active |
| **API** | Admin Login Request | `huit.api.admin-login-request` | `AdminLoginRequest` (Pydantic) | `adminApi.login` | N/A | Active |
| **API** | Admin Login Response | `huit.api.admin-login-response` | `AdminLoginResponse` (Pydantic) | `adminApi.login` | N/A | Active |
| **API** | Admin Session Response | `huit.api.admin-session-response` | `AdminSessionResponse` (Pydantic) | `adminApi.checkSession` | N/A | Active |
| **Stream** | Chat Event (NDJSON v2) | `huit.stream.chat-event` | `StreamEventEnvelope` (Pydantic) | `ndjsonParser` + `useChatStream` | N/A | Active |
| **Stream** | Chat Event (Legacy Boundary) | `huit.stream.chat-event-legacy-boundary` | NDJSON Boundary parser | `ndjsonParser` legacy fallback | N/A | Active |
| **Queue** | Background Job Input | `huit.queue.job-input` | `validate_job_input` (job_queue) | N/A | N/A | Active |
| **Queue** | Background Job Result | `huit.queue.job-result` | `validate_job_result` (job_queue) | N/A | N/A | Active |
| **Queue** | Background Job Error | `huit.queue.job-error` | `validate_job_error` (job_queue) | N/A | N/A | Active |
| **Queue** | Worker Retry Metadata | `huit.queue.retry-metadata` | `validate_retry_metadata` (job_queue) | N/A | N/A | Active |
| **Queue** | Dead Letter Queue Metadata | `huit.queue.dead-letter-metadata` | Planned (bảo lưu contract) | N/A | N/A | Planned |
| **MongoDB** | Operation Audit Record | `huit.mongo.operation-audit` | `MongoOperationAuditRecord` | N/A | `$jsonSchema` (018, 021) | Active |
| **MongoDB** | Schema Registry Record | `huit.mongo.schema-registry-record` | Migration 022 builder | N/A | `$jsonSchema` (022) | Active |
| **MongoDB** | Physical Asset / Blob Record | `huit.mongo.asset-record` | `MongoAssetRecord` | N/A | `$jsonSchema` (008, 017) | Active |
| **MongoDB** | Artifact Document Record | `huit.mongo.artifact-record` | `MongoArtifactRecord` | N/A | `$jsonSchema` (010) | Active |
| **MongoDB** | Background Job Record | `huit.mongo.job-record` | `MongoJobRecord` | N/A | `$jsonSchema` (008, 015) | Active |
| **MongoDB** | Generated Image Record | `huit.mongo.generated-image-record` | `MongoGeneratedImageRecord` | N/A | `$jsonSchema` (008, 015) | Active |
| **MongoDB** | Admin Session Document | `huit.mongo.admin-session-document` | `AdminSessionDocument` | N/A | `$jsonSchema` (020) | Active |
| **MongoDB** | Query Cache Document | `huit.mongo.query-cache-record` | `MongoQueryCacheRecord` | N/A | `$jsonSchema` (008) | Active |
| **MongoDB** | RAG Telemetry Event Record | `huit.mongo.rag-event-record` | `MongoRagEventRecord` | N/A | `$jsonSchema` (008, 019) | Active |
| **MongoDB** | Admission Visual Document | `huit.mongo.admission-visual-record` | `MongoAdmissionVisualRecord` | N/A | `$jsonSchema` (008, 016) | Active |
| **MongoDB** | HUIT Knowledge Base Record | `huit.mongo.huit-kb-record` | `MongoHuitKbRecord` | N/A | `$jsonSchema` (018) | Active |
