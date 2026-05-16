# Document Ingest Contract

This contract freezes the document-ingest behavior that future document-pipeline work must
preserve.

## Ownership Decision

The API/control-plane path is the canonical owner of document-ingest semantics:

- project context hydration
- document classification
- document diffing
- persistence
- review creation
- user-facing notification decisions

The worker is an artifact collector and event producer. Its compatibility ingest helper must
delegate document writes through the canonical `DocumentIngestService` path instead of owning
classification, diffing, persistence, review creation, or audit semantics itself.

## Required Behavior

- The ingest path must hydrate missing `source_status_text` and `project_state` from the stored
  project before classification.
- A retried artifact with the same bytes, tenant, project, document type, and phase is idempotent:
  it returns the existing document and creates no new diff or review rows.
- A changed artifact in the same document type and phase supersedes the current document and
  creates one diff row.
- A changed TOR diff creates a pending review. TOR change notifications remain deferred until a
  review is approved.
- Worker ingestion must not create a second document for an API-ingested artifact merely because
  the worker payload omitted project status/state context.

## Locked Tests

The contract is covered by `tests/phase3/test_document_ingest_contract.py`:

- `test_api_and_worker_document_ingest_share_project_context_contract`
- `test_cross_path_document_retry_is_idempotent`
- `test_worker_document_ingest_routes_through_canonical_service_boundary`

PR 10 moved worker writes behind the canonical service boundary; these tests should continue to
pass during later cleanup and observability work.

## Final Pipeline

1. API requests and worker artifact collection both enter `DocumentIngestService`.
2. `DocumentIngestService` hydrates project context and calls `SqlDocumentRepository.store_document`.
3. `SqlDocumentRepository.store_document` owns hashing, classification, duplicate replay checks,
   blob writes, supersession, diff creation, and review creation.
4. `DocumentIngestService` owns document-created audit events and exposes the result to callers.

The worker must not bypass this service/repository boundary to implement its own classification,
diffing, persistence, review, audit, or notification semantics.

## Observability

The canonical path emits structured log events that can be searched across API and worker runs:

- `document_ingest_canonical_started`
- `document_ingest_canonical_succeeded`
- `document_store_duplicate_replay_detected`
- existing storage events such as `document_store_write_plan_resolved`,
  `document_store_primary_write_succeeded`, and `document_store_failed_before_cleanup`

Duplicate replay events are expected for retried artifacts with the same tenant, project, SHA-256,
document type, and document phase. They should return the existing document and must not create new
diff or review rows.
