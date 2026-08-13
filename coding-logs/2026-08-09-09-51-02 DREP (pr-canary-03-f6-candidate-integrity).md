# DREP: PR-CANARY-03 F6 + candidate identity — Candidate-Attempt Integrity (v3, lifecycle reconciliation)

> Slice charter: canonical table rows **F6** and **identity** in
> `coding-logs/2026-08-09-09-45-52 Coding Log (pr-canary-03-remediation-reconciliation).md`.
> Source findings: consolidated review 2026-08-06 07:48:44 — HIGH 6 + MEDIUM 3,
> plus the F1-log deferral ("conflict REJECTED distinctly → F6 slice") and the
> F2 DREP §9-D resume re-key deferral.
> v3 preserves and reconciles the earlier Codex adversarial pass (gpt-5.6-sol,
> xhigh) — every finding is dispositioned in the **Synthesis record** at the end.

## §0 Repo Profile

- **Languages:** project contract Python 3.12+; the worktree venv currently runs
  Python 3.13.5 (`uv` is not on PATH, so all gates use locked `.venv` tools).
  `uv.lock` remains the release source of truth; SQLAlchemy 2.0.51.
  TypeScript exists (`apps/web`) but is untouched (no API contract change).
- **Worktree:** `/Users/subhajlimanond/dev/egp-canary03`, branch
  `feat/canary-03-f6-candidate-integrity` at `4173dc4431ceb2703cab015b01d2865954fc8297`
  (== `origin/main` after the 2026-08-13 refresh). Own `.venv`; PostgreSQL binaries (initdb/pg_ctl/psql)
  verified PRESENT locally, so the real-Postgres gates RUN here (no silent skip).
- **Test:** `./.venv/bin/python -m pytest tests/phase1/... -q` (focused);
  full: `./.venv/bin/python -m pytest tests/ apps/ packages/ -q`.
- **Lint:** `./.venv/bin/python -m ruff check apps/ packages/ tests/ scripts/`
  (+ `ruff format`).
- **Typecheck:** `./.venv/bin/python -m compileall apps packages`.
- **Migration policy:** `docs/MIGRATION_POLICY.md` — next unused prefix = `039`
  (allocated by #207); never rename applied files; manifest via
  `scripts/check_migration_manifest.py` (`write_manifest`).
- **Real-Postgres harness:** `egp_db.dev_postgres.TempPostgresCluster` +
  `egp_db.migration_runner.apply_migrations`, gated on
  `postgres_binaries_available()` (pattern: `tests/phase1/test_candidate_postgres_dialect.py:95`).
- **Coding log:** `coding-logs/2026-08-09-09-51-02 Coding Log (pr-canary-03-f6-candidate-integrity).md`;
  `.codex/coding-log.current` points at it.
- **External-model authority:** the user explicitly selected the g2 lifecycle.
  No repository content is delegated for F6 because every slice is PRIMARY by
  Q1 (migration, tenant integrity, concurrency, or cross-package identity
  contract); the DeepSeek route and doctor are therefore not exercised.
- **Ownership:** repo `ours` · runtime `ours` · disposition `production`.
- **Repo MUST NOT list (restated):** no cross-tenant access — every query
  tenant-scoped (existing exception: `reconcile_open_candidates` is run_id-only —
  **F5's charter**, not fixed here); workers emit events only (this ledger is
  worker-plane accounting, not product state); typed signatures; ≤50-line
  functions preferred; TDD; real DB for integration tests (T-3); never rename
  applied migrations; never amend `038` in place; no secrets in logs.

## §1 Goal / Non-Goals

Make the candidate-attempt ledger structurally trustworthy before F4 builds run
authority on it: PostgreSQL-enforced tenant/parent integrity, a typed terminal
vocabulary (rich enough for F4's detail-anomaly terminalization), Python-layer
vocabulary validation, distinct idempotent-replay vs contradiction semantics
that are VISIBLE at the production call sites, and a content-based candidate
identity (normalized keyword + project-number or the complete visible
name/organization/budget/status signature) that is stable
across browser-death resume re-scans.

**Non-Goals** (chartered owners — do not implement here):
- Wiring `finalize_dropped`, ledger-derived run/keyword outcomes, forbidding
  success with open rows — **F4**.
- New reconciliation loss paths, tenant-scoping `reconcile_open_candidates`,
  agent-runtime reconciliation — **F5**. (This slice DOES retype the four
  existing dispatcher reason literals — vocabulary conformance only, no
  control-flow change.)
- Fault injection — **F7**. Observability/capture/retention — **F8**.
- Scan-time dedup semantics in `browser_discovery.py` (product behavior: which
  rows get accepted/persisted). The ledger key gets FINER than the dedupe key;
  the dedupe key itself is untouched.
- No data backfill of `row_marker`/`project_number` for pre-039 rows.

## §2 Requirements

- **R1** PostgreSQL rejects a candidate row whose `(tenant_id, run_id)` does not
  reference a `crawl_runs` row of the same tenant (composite FK + new
  `UNIQUE (tenant_id, id)` on `crawl_runs`).
- **R2** PostgreSQL rejects a non-NULL `(tenant_id, project_id)` that does not
  reference a `projects` row of the same tenant — including a nonexistent
  project id — (composite FK + new `UNIQUE (tenant_id, id)` on `projects`);
  NULL `project_id` always passes.
- **R3** `terminal_reason` accepts only the typed vocabulary (or NULL):
  (a) vocabulary defined once as `CandidateTerminalReason`; (b) migration 039's
  repair list and CHECK list are identical, the latest vocabulary-defining
  CHECK equals the enum, and historical lists remain subsets so later
  fix-forward vocabulary extensions do not rewrite applied history; (c) the
  repository REJECTS (ValueError) any non-member reason at the
  Python layer; (d) the four dispatcher reconcile literals become enum values.
- **R4** Status/reason/project combinations are DB-enforced over the full
  matrix: `accepted` → (reason NULL, project NULL); `persisted` → (reason NULL,
  project NOT NULL); `dropped`/`failed`/`unknown` → (reason NOT NULL, project NULL).
- **R5** The workflow stores no raw exception text in `terminal_reason`: the
  REAL `_persist_discovered_project` exception handler writes
  `CandidateTerminalReason.PERSIST_ERROR` + truncated text in `terminal_detail`,
  proven by a workflow-level test that exercises that handler.
- **R6** `_finalize` distinguishes outcomes field-wise over
  (status, terminal_reason, project_id-normalized): identical replay returns the
  existing record; ANY single-field divergence raises
  `CandidateTerminalConflictError`; missing row returns `None`.
- **R7** `compute_candidate_key` is content-based. It SHA-256 hashes compact
  JSON for `["egp-candidate-key.v2", keyword.strip().casefold(), ...identity]`.
  A truthy project number yields `['num', project_number.casefold()]`; otherwise
  identity is `['name', project_name.casefold(), organization_name.casefold(),
  budget_text.casefold(), source_status_text.casefold()]`. JSON encoding prevents
  delimiter-injection collisions. Visible fields get casefold ONLY (no
  strip/collapse), and page/ordinal never influence the key, so resume re-scans
  are idempotent via ON CONFLICT.
- **R8** Acceptance stores content provenance: new nullable `project_number` and
  `row_marker` columns; `row_marker` is canonical JSON stored opaquely as TEXT.
  The live path populates project number and the complete visible marker. The
  direct/materialized path forwards its contracted project number,
  organization, and source status fields; it does not fabricate browser-only
  `budget_text`. No path fabricates `0,0` coordinates.
- **R9** Migration `039` is safe on any 038-era data: non-vocab reasons →
  `unclassified` with original preserved in `terminal_detail`; shape-invalid
  rows repaired with ALL displaced values preserved into `terminal_detail`
  (never silently discarded); orphan-run rows (incl. cross-tenant-parent rows)
  deleted — counts must be recorded at production apply time (runbook note in
  PR); orphan-project rows → `unknown`/`unclassified`, project NULL.
- **R10** Existing suites stay green after in-plan updates; manifest
  regenerated; SQLite mirror carries columns + CHECKs (enforced by SQLite) but
  NOT the composite FKs (034-precedent; PostgreSQL tests are the FK oracle and
  they run locally).
- **R11** A contradictory finalize at the production call sites is DISTINCTLY
  visible: both workflow finalize blocks catch `CandidateTerminalConflictError`
  separately from generic `Exception` and log a structured
  `candidate_terminal_conflict` event with existing-vs-requested triples
  (fail-open continues — escalation to run authority is F4).

## §3 Change Contract

| ID | Path | Action | Anchor | New exports | Purpose |
|----|------|--------|--------|-------------|---------|
| F1 | `packages/db/src/migrations/039_candidate_attempt_integrity.sql` | MIGRATION | — | — | columns, repair, parent unique keys, composite FKs, CHECKs |
| F2 | `packages/db/src/migrations/manifest.sha256` | MODIFY | regenerate | — | include 039 |
| F3 | `packages/shared-types/src/egp_shared_types/enums.py` | MODIFY | `CandidateTerminalReason` | `CandidateTerminalReason` | typed vocabulary (16 values) |
| F4 | `packages/shared-types/src/egp_shared_types/__init__.py` | MODIFY | enum imports + `__all__` | re-export | package surface |
| F5 | `packages/db/src/egp_db/repositories/candidate_attempt_repo.py` | MODIFY | table definition; `record_accepted`; `_finalize`; terminal helpers; `reconcile_open_candidates` | `CandidateTerminalConflictError` | columns; field-wise replay/conflict; `terminal_detail`; provenance params; Python vocab validation |
| F6 | `packages/db/src/egp_db/repositories/__init__.py` | MODIFY | candidate repository exports | re-export error | package surface |
| F7 | `packages/crawler-core/src/egp_crawler_core/candidate_key.py` | MODIFY | whole file | — | content-based key |
| F8 | `apps/worker/src/egp_worker/workflows/discover.py` | MODIFY | `run_discover_workflow._persist_discovered_project`; `_record_live_candidate`; both finalize handlers | — | new key inputs; provenance; typed failure reason+detail; distinct conflict logging (R11) |
| F9 | `apps/api/src/egp_api/services/discovery_worker_dispatcher.py` | MODIFY | `dispatch_cancellable` terminal branches; `_reconcile_candidate_attempts`; `terminate_active_runs` | — | R3(d): literals → `CandidateTerminalReason.X.value`; NO control-flow change |
| F10 | `tests/phase1/test_candidate_postgres_dialect.py` | MODIFY | PostgreSQL candidate fixture seeding | — | seed real run+project so 039's FKs pass |

## §4 Function Contracts

```
FN1  compute_candidate_key(keyword: str, project_name: str,
                           project_number: str | None = None,
                           organization_name: str = "",
                           budget_text: str = "",
                           source_status_text: str = "") -> str
     File: F7
     Does: SHA-256 hex of compact JSON containing version, normalized keyword,
           and either project number or the full visible fallback signature.
     Pre:  raw values as produced by the scan/payload; caller does NOT pre-normalize.
     Post: position-independent; stable across resume; per-keyword distinct
           (cross-keyword duplicate rows are F4's duplicate_in_run).
     Errors: none (pure).
     Invariants: name/org/budget/status/number are casefold-ONLY (no
           strip/collapse); JSON array domains prevent cross-field and
           delimiter collisions. Keyword
           normalization mirrors discovery_authorization.normalize_keyword + the
           casefold comparison (discovery_authorization.py:73-96).
     Signature change: page_number/row_ordinal REMOVED; org added. All callers
           (F8 x2) and tests updated; `rg compute_candidate_key --glob "*.py"`
           must show only F7/F8/tests.
```

```
FN2  class CandidateTerminalReason(StrEnum)   (F3) — 16 values, and EXACTLY
     these in every 039 list (T15 checks all IN/NOT IN lists in the file):
       WORKER_LOST="worker_lost"  LEASE_LOST="lease_lost"
       WORKER_TIMEOUT="worker_timeout"  WORKER_TERMINATED="worker_terminated"
       CANCELLED="cancelled"                      # chartered F5
       PERSIST_ERROR="persist_error"              # F8 failure path (this PR)
       DUPLICATE_IN_RUN="duplicate_in_run"        # chartered F4 (dedup drop)
       LATE_STAGE="late_stage"                    # chartered F4 (non-discoverable stage)
       UNCLASSIFIED="unclassified"                # 039 legacy normalization ONLY
       # detail-terminal reasons so F4 can terminalize accepted rows precisely
       # (mirrors ProjectDetailReason values; Codex finding 10):
       NAVIGATION_FAILURE="navigation_failure"
       RESULTS_PAGE_RETURNED="results_page_returned"
       MISSING_REQUIRED_FIELDS="project_detail_missing_required_fields"
       REJECTION_PAGE="rejection_page"
       PLACEHOLDER_DETAIL="placeholder_detail"
       OUT_OF_SCOPE_STAGE="out_of_scope_stage"
       DETAIL_UNKNOWN="detail_unknown"            # ProjectDetailReason.UNKNOWN mapped
     (16 total; T15 pins the authoritative SQL CHECK to this exact set.)
```

```
FN3  class CandidateTerminalConflictError(RuntimeError)   (F5)
     Attributes: tenant_id, run_id, candidate_key, existing_status,
                 existing_reason, existing_project_id, requested_status,
                 requested_reason, requested_project_id (str | None).
     Message: one line, candidate_key + both triples; NO payload/exception text.
```

```
FN4  _finalize(tenant_id, run_id, candidate_key, new_status,
               terminal_reason=None, project_id=None, terminal_detail=None)
         -> CandidateAttemptRecord | None          (F5)
     Does: validate terminal_reason ∈ CandidateTerminalReason (or None) — else
           ValueError BEFORE any SQL (R3c). UPDATE ... WHERE status='accepted'
           (unchanged). On rowcount==0, SELECT in the same transaction:
             absent → None
             field-wise identical (status == new_status AND reason ==
               terminal_reason AND normalize_uuid_string-compared project_id)
               → return existing record
             ANY field differs → raise CandidateTerminalConflictError
     terminal_detail is diagnostics ONLY: excluded from the replay comparison
           (first write wins — explicitly non-authoritative; Codex finding 11
           accepted as documented).
     Comparison normalizes requested project_id via normalize_uuid_string before
           comparing to the stored canonical value (Codex finding 6).
```

```
FN5  finalize_failed(..., terminal_reason: str, terminal_detail: str | None = None)
     finalize_dropped(..., terminal_reason: str, terminal_detail: str | None = None)
     finalize_persisted(...) unchanged (reason/detail NULL).
     reconcile_open_candidates(run_id, terminal_reason: str =
         CandidateTerminalReason.WORKER_LOST.value) — signature otherwise
         UNTOUCHED (F5's charter); gains the same vocabulary ValueError guard.
     All delegate to FN4 / share the validator.
```

```
FN6  record_accepted(..., project_number: str | None = None,
                     row_marker: str | None = None) -> CandidateAttemptRecord   (F5)
     row_marker: caller-serialized compact JSON (sort_keys, ensure_ascii=False);
     stored opaquely. CandidateAttemptRecord gains project_number / row_marker /
     terminal_detail fields; _record_from_mapping (sole constructor —
     Codex-verified) maps them.
```

```
FN7  discover.py changes                       (F8)
     _record_live_candidate:
       marker = candidate_info.get("row_marker") — dict from
         _build_results_row_marker (has organization_name; browser callback
         payload verified at browser_discovery.py:687-696)
       key = compute_candidate_key(
           keyword=candidate_keyword,
           project_name=str(candidate_info.get("project_name") or ""),
           project_number=(str(candidate_info["project_number"]) if
                           candidate_info.get("project_number") else None),
           organization_name=str((marker or {}).get("organization_name") or ""),
           budget_text=str((marker or {}).get("budget_text") or ""),
           source_status_text=str((marker or {}).get("source_status_text") or ...))
       record_accepted(..., page/ordinal ints when present (storage unchanged),
           project_number=<same>, row_marker=json.dumps(marker, sort_keys=True,
           ensure_ascii=False, separators=(",", ":")) if isinstance(marker, dict) else None)
     Direct path: key from contracted discovered project_number/project_name/
       organization_name/source_status_text. Browser-only budget_text stays
       absent; coordinate 0-defaults disappear; stores project_number;
       row_marker=None.
     Failure finalize: finalize_failed(...,
       terminal_reason=CandidateTerminalReason.PERSIST_ERROR.value,
       terminal_detail=str(exc)[:500])
     BOTH finalize blocks restructured (R11):
       except CandidateTerminalConflictError as conflict:
           logger.error("Candidate terminal conflict for %s", key, extra={
               "egp_event": "candidate_terminal_conflict", "tenant_id": ...,
               "run_id": ..., "candidate_key": ..., existing/requested triples})
       except Exception:
           logger.warning(<existing message>, exc_info=True)
       (fail-open in both branches — authority is F4.)
```

Migration F1 statement order (single-shot SQL — the runner's filename ledger
prevents replay; the statements themselves are NOT idempotent and never re-run):
1. `ADD COLUMN project_number TEXT; ADD COLUMN row_marker TEXT; ADD COLUMN terminal_detail TEXT;`
2. Non-vocab reason preservation+normalization:
   `UPDATE ... SET terminal_detail = terminal_reason, terminal_reason='unclassified'
    WHERE terminal_reason IS NOT NULL AND terminal_reason NOT IN (<vocab>);`
3. Referential repair (counts recorded at apply time — PR runbook):
   `DELETE FROM discovery_candidate_attempts a WHERE NOT EXISTS (SELECT 1 FROM
    crawl_runs r WHERE r.id = a.run_id AND r.tenant_id = a.tenant_id);`
   -- also removes cross-tenant-parent rows (run exists under another tenant)
   `UPDATE discovery_candidate_attempts a SET project_id = NULL,
    candidate_status='unknown', terminal_reason='unclassified',
    terminal_detail = COALESCE(terminal_detail, 'migration_039_orphan_project')
    WHERE a.project_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM projects p
    WHERE p.id = a.project_id AND p.tenant_id = a.tenant_id);`
4. Shape repair — ALWAYS preserving displaced evidence (Codex finding 9 fix):
   `UPDATE ... SET terminal_reason='unclassified', terminal_detail =
    COALESCE(terminal_detail,'migration_039_missing_reason')
    WHERE candidate_status IN ('dropped','failed','unknown') AND terminal_reason IS NULL;`
   `UPDATE ... SET candidate_status='unknown', terminal_reason='unclassified',
    terminal_detail = COALESCE(terminal_detail,'migration_039_persisted_without_project'),
    project_id = NULL WHERE candidate_status='persisted' AND project_id IS NULL;`
   `UPDATE ... SET terminal_detail = COALESCE(terminal_detail, terminal_reason),
    terminal_reason = NULL WHERE candidate_status IN ('accepted','persisted')
    AND terminal_reason IS NOT NULL;`   -- preserve-then-clear, never drop
   `UPDATE ... SET project_id = NULL WHERE candidate_status IN
    ('accepted','dropped','failed','unknown') AND project_id IS NOT NULL;`
5. `ALTER TABLE crawl_runs ADD CONSTRAINT crawl_runs_tenant_id_id_key UNIQUE (tenant_id, id);`
   `ALTER TABLE projects  ADD CONSTRAINT projects_tenant_id_id_key  UNIQUE (tenant_id, id);`
6. `ALTER TABLE discovery_candidate_attempts
     ADD CONSTRAINT dca_tenant_run_fkey FOREIGN KEY (tenant_id, run_id)
       REFERENCES crawl_runs (tenant_id, id) ON DELETE CASCADE,
     ADD CONSTRAINT dca_tenant_project_fkey FOREIGN KEY (tenant_id, project_id)
       REFERENCES projects (tenant_id, id),
     ADD CONSTRAINT dca_terminal_reason_vocab_check CHECK (
       terminal_reason IS NULL OR terminal_reason IN (<vocab>)),
     ADD CONSTRAINT dca_status_shape_check CHECK (
       (candidate_status='accepted'  AND terminal_reason IS NULL     AND project_id IS NULL) OR
       (candidate_status='persisted' AND terminal_reason IS NULL     AND project_id IS NOT NULL) OR
       (candidate_status IN ('dropped','failed','unknown')
                                     AND terminal_reason IS NOT NULL AND project_id IS NULL));`
   -- run FK cascades (crawl_tasks.run_id + 034_crawler_agent_results.sql:120
   -- precedent: a deleted run takes its accounting; ledger rows for a deleted
   -- run are meaningless). project FK is NO ACTION: nothing deletes projects,
   -- and SET NULL would violate dca_status_shape_check for persisted rows.

SQLAlchemy mirror (F5): + three Columns + both CHECKs. Composite FKs and parent
uniques stay SQL-only — 034 precedent verified (crawler_agent_repo mirrors its
own uniques/CHECKs but no composite FK; discovery_jobs mirror carries no
(tenant_id,id) unique). DIVERGENCE IS EXPLICIT: bootstrap/SQLite schemas do not
enforce referential integrity; the PostgreSQL suite (which runs locally —
binaries verified) is the integrity oracle.

## §5 Test Plan

New file `tests/phase1/test_candidate_integrity_migration.py` (T1-T6 real
Postgres via TempPostgresCluster+apply_migrations, skip-gated; T15 pure parse,
NOT gated). Fixture helper seeds tenants A,B + one run and one project per
tenant via SQL.

```
T1   test_candidate_insert_rejects_cross_tenant_run
     Covers: R1. Insert candidate (tenant A, run of B) → IntegrityError naming
     dca_tenant_run_fkey; positive control (A, run of A) succeeds.
     RED-proof: pre-039 both inserts succeed → pytest.raises "DID NOT RAISE".
T2   test_candidate_insert_rejects_nonexistent_run
     Covers: R1. Random run_id → IntegrityError. RED: "DID NOT RAISE".
T3   test_candidate_project_fk_same_tenant_only_null_and_nonexistent
     Covers: R2. persisted+project of tenant B → IntegrityError;
     persisted+NONEXISTENT project uuid → IntegrityError (Codex 1d);
     persisted+project of tenant A → OK; accepted+NULL project → OK.
     RED: cross-tenant UPDATE succeeds pre-039 → "DID NOT RAISE".
T4   test_terminal_reason_vocabulary_enforced
     Covers: R3(SQL). failed + free text → IntegrityError
     (dca_terminal_reason_vocab_check); failed + 'persist_error' → OK.
     RED: "DID NOT RAISE".
T5   test_status_shape_full_matrix
     Covers: R4. PARAMETRIZED full cartesian: status ∈ {accepted, persisted,
     dropped, failed, unknown} × reason ∈ {NULL, 'worker_lost'} × project ∈
     {NULL, valid same-tenant project}: all 20 tuples, each asserting the exact
     legality table of R4 (5 valid tuples across 3 shape categories, 15 invalid).
     RED: pre-039 all 20 succeed → first invalid tuple "DID NOT RAISE".
T6   test_migration_039_repairs_pre_existing_038_data
     Covers: R9. Stepwise: copy 001..038 to tmp dir; apply; seed; insert legacy
     rows: (a) failed + free-text reason; (b) accepted + orphan run;
     (c) persisted + orphan project; (d) candidate of tenant A referencing a run
     OWNED BY B (cross-tenant parent, pre-039 legal); (e) accepted +
     reason 'worker_lost' (typed-but-shape-invalid). Apply full dir. Assert:
     (a) reason 'unclassified', detail == original; (b) deleted; (c) unknown/
     'unclassified'/project NULL/detail marker; (d) DELETED (run lookup is
     tenant-matched); (e) reason NULL **and detail == 'worker_lost'**
     (preserve-then-clear; Codex 9); all survivors satisfy both CHECKs
     (SELECT count of violations == 0 via NOT/CASE re-expression).
     RED-proof: with 039 absent the "full dir" == 038 → (a) keeps free text →
     AssertionError on value.
T7   test_finalize_identical_replay_returns_existing_record
     File: tests/phase1/test_candidate_accounting.py. Covers: R6.
     record_accepted → finalize_failed('persist_error', detail='x') →
     finalize_failed('persist_error', detail='different') returns record
     (status 'failed'); detail still 'x'. RED: current returns None.
T8   test_finalize_contradiction_raises_typed_conflict  (parametrized — Codex 6)
     Covers: R6. Cases, each from a fresh accepted+finalized row:
       (a) persisted(P1) then failed('persist_error')        [status differs]
       (b) failed('persist_error') then failed('worker_lost') [reason only differs]
       (c) persisted(P1) then persisted(P2)                   [project only differs]
       (d) persisted(P1) then persisted(P1-UPPERCASED with surrounding whitespace) → NO raise,
           returns record (normalize_uuid_string comparison)
     Assert attributes carry both triples. RED: (a)-(c) return None today
     ("DID NOT RAISE"); (d) TypeError until FN4 lands.
T9   test_finalize_missing_row_returns_none — unchanged semantics guard.
     Covers: R6. Mutation evidence: a raising-on-missing impl fails it.
T10  test_record_accepted_stores_provenance_columns
     Covers: R8. project_number+row_marker round-trip; omitted → NULL.
     RED: TypeError (unexpected kwarg).
T11  test_finalize_failed_stores_typed_reason_and_detail_and_rejects_nonvocab
     Covers: R3(c), R5(repo half). finalize_failed('persist_error', detail=...)
     stores both; finalize_failed('Boom: Traceback') raises ValueError BEFORE SQL
     (assert no row mutated). RED: TypeError (no detail param) + free text
     currently stored happily.
T12  test_candidate_key_golden_vectors
     Covers: R7. Assert EXACT digests: for fixed inputs, expected is computed
     in-test from the compact JSON v2 formula and then SHA-256 hashed
     from the spec formula (independent of F7's implementation path; a
     constant-hash or wrong-formula impl fails — Codex 7-T12). Also
     inspect.signature has no page/ordinal params.
     RED: TypeError (old signature requires page_number).
T13  test_candidate_key_normalization_and_identity_partition
     Covers: R7. (a) keyword " TOR " == "tor" (strip+casefold); (b) same name,
     different org, no number → DIFFERENT keys (org in identity); (c) same
     number, different name/org → SAME key (number wins); (d) name identity is
     casefold-only: internal double-space vs single-space → DIFFERENT keys
     (finer-not-coarser invariant); (e) "num:X" never collides with a name
     literally "num:X" (prefix separation: name-identity includes "|org:").
     RED: TypeError (old signature).
T14  test_live_candidate_callback_persists_content_provenance
     File: tests/phase1/test_worker_live_discovery.py — extend the existing
     real-SQLite-repo harness (L2982-3160: fake crawl_live_discovery invokes the
     workflow's candidate_callback; repo row read back).
     Covers: R7, R8 (workflow half). Callback payload includes org-bearing
     row_marker; assert stored row: project_number column, row_marker JSON
     (sorted keys, exact string), candidate_key == in-test hashlib golden
     recomputation (NOT the helper — Codex 7-T14/T16), page/ordinal stored ints.
     Browser-side construction of the callback payload is pinned by the existing
     F2 live-discovery tests (payload shape at browser_discovery.py:687-696).
     RED: TypeError at record_accepted (unexpected kwargs) pre-F5/F8.
T15  test_terminal_reason_vocabulary_drift_guard
     Covers: R3(b). Parse 039's repair and CHECK lists and assert they are
     equal; assert the latest vocabulary-defining CHECK equals the enum; assert
     historical lists remain subsets. RED/mutation proof: deleting one value
     from 039's repair list fails the 039-equality assertion.
T16  test_direct_path_key_is_content_based_no_fabricated_coordinates
     File: tests/phase1/test_worker_live_discovery.py. Covers: R7, R8 (direct path). Materialized payload with
     project_number + organization_name, NO page/row values → ledger row:
     candidate_key == in-test hashlib golden recomputation; page/ordinal NULL
     (not 0); project_number stored. RED: today's key uses (kw,0,0,name) →
     golden mismatch AssertionError. Companion
     `test_direct_path_no_number_identity_uses_org_and_status` proves all
     contracted fallback fields are forwarded. No direct-path budget contract
     is introduced by this slice.
T17  test_workflow_persist_failure_writes_typed_reason  (NEW — Codex 1c/7-T11)
     File: tests/phase1/test_worker_live_discovery.py. Covers: R5 (workflow half).
     Harness: run_discover_workflow with real SQLite repo + FakeProjectEventSink
     whose record_discovery RAISES. Assert the REAL handler (L665-680) produced:
     row status 'failed', reason 'persist_error', detail contains the exception
     message (truncated ≤500). RED: today the row's reason == raw str(exc)
     → AssertionError on 'persist_error'.
T18  (folded into existing dispatcher suites) — F9 changes literals to enum
     .value with values UNCHANGED ('lease_lost'/'worker_timeout'/
     'worker_terminated'/'worker_lost'), so the existing dispatcher reconcile
     tests keep passing; no new test. Covers R3(d) jointly with T15 (vocabulary
     contains all four) and compileall (import wiring).
T19  test_workflow_logs_distinct_event_on_terminal_conflict  (NEW — R11)
     File: tests/phase1/test_worker_live_discovery.py. Arrange: real SQLite repo;
     PRE-finalize the key as failed('worker_lost') by computing the content key
     in-test; then run workflow persistence success for the same candidate.
     Assert: caplog captures egp_event == "candidate_terminal_conflict" (ERROR)
     with both triples; the workflow CONTINUES (project persisted; no raise).
     RED: today _finalize returns None silently → no such log record →
     AssertionError on caplog scan.
```

Existing tests to update (diff-audit allowlist):
- `test_candidate_accounting.py::test_finalize_failed_does_not_overwrite_terminal_state`
  (L67-97): semantic rewrite → expects `CandidateTerminalConflictError` +
  preserved state (merges with T8; keep summary asserts).
- Key-construction tests (L165-215) + any old-signature callers in
  `test_worker_live_discovery.py`: mechanical signature updates.
- `test_candidate_postgres_dialect.py` (F10): seed a real run + project for the
  tenant; keep its dialect/idempotency assertions intact (Codex 5 — it would
  otherwise fail 039's FKs).
Sweep verified: the only non-vocab reason literal in the suite is the
`"some error"` in the rewritten test; SQLite ENFORCES the new CHECKs, giving the
unit suite a real constraint oracle.

## §6 Traceability Matrix

| Req | Fulfilled at — realizing call site | Tests | Files | Slice |
|-----|-------------------------------------|-------|-------|-------|
| R1 | 039 step 5 (crawl_runs unique) + step 6 dca_tenant_run_fkey | T1,T2 | F1 | S1 |
| R2 | 039 step 5 (projects unique) + step 6 dca_tenant_project_fkey | T3 | F1 | S1 |
| R3 | (a) FN2 enum (F3); (b) 039 lists ← T15; (c) FN4 validator first statement (F5); (d) F9 terminal branches + helper default | T4,T15,T11,T18 | F1,F3,F5,F9 | S1,S2 |
| R4 | 039 step 6 dca_status_shape_check | T5 | F1 | S1 |
| R5 | `_persist_discovered_project` exception handler → finalize_failed(PERSIST_ERROR, detail) (FN7) | T17 (workflow), T11 (repo) | F5,F8 | S3 |
| R6 | FN4 rowcount==0 branch in `_finalize` | T7,T8,T9 + rewritten L67 test | F5,F6 | S2 |
| R7 | FN1 body + BOTH call sites: `_record_live_candidate`; direct/materialized acceptance | T12,T13,T14,T16 | F7,F8 | S3 |
| R8 | FN6 values dict; live call site marker-JSON+visible fields; direct site number+org+status | T10,T14,T16 | F5,F8 | S2,S3 |
| R9 | 039 steps 2-4 (preserve-then-clear) + step 3 deletes | T6 | F1 | S1 |
| R10 | manifest (F2); mirror columns+CHECKs (F5); F10 fixture upgrade; full-suite gate | T6, full suite | F2,F5,F10 | S1-S3 |
| R11 | BOTH workflow finalize blocks: `except CandidateTerminalConflictError` branch logging `candidate_terminal_conflict` (FN7) | T19 | F8 | S3 |

## §7 Wiring Verification

| New component | Entry point (runtime caller) | Registration | Schema/table |
|---|---|---|---|
| 039 SQL | `apply_migrations` sorted order | prefix 039 + manifest | `discovery_candidate_attempts`, `crawl_runs`, `projects` (grep-verified 001/038) |
| `CandidateTerminalReason` | discover.py failure handler; dispatcher reconcile literals; repo validator | imports in F8/F9/F5; re-export F4 | CHECK lists (T15) |
| `CandidateTerminalConflictError` | raised in `_finalize`; caught DISTINCTLY at both workflow finalize blocks (R11) | defined F5, exported F6, imported F8 | — |
| provenance params | live + direct acceptance call sites | existing factory wiring unchanged (main.py:167, agent_runtime.py:223) | 039 columns + mirror |
| new record fields | `_record_from_mapping` (sole constructor — Codex-verified) | dataclass F5 | same columns |
| content key | both F8 call sites | existing import discover.py:18 | `candidate_key` column |

## §8 Slice Plan

| ID | Scope | Owner | Q0-Q3 result | Stop line | Production allowlist | Oracle | Done when |
|----|-------|-------|--------------|-----------|----------------------|--------|-----------|
| S1 | F1,F2,F3,F4 + T1-T6,T15 | **PRIMARY** | Q1: migration + tenant integrity | PRIMARY | none | T1-T6 real-PG; T15; manifest | fresh + seeded-038 apply green; mutation proof for strengthened T15 |
| S2 | F5,F6,F9,F10 + T7-T11 | **PRIMARY** | Q1: concurrency + shared contract | PRIMARY | none | T7-T11 + candidate/dialect/dispatcher suites | green; full conflict triples; exports wired |
| S3 | F7,F8 + T12-T14,T16,T17,T19 | **PRIMARY** | Q1: cross-package identity contract | PRIMARY | none | T12-T19 + live-discovery + golden vectors | budget forwarding RED→GREEN; `rg compute_candidate_key` clean |

All three remain primary-owned: migration authority (S1), a shared-contract + API-file
touch (S2), and the identity invariant whose oracle is partly judgment (S3
golden vectors pin the formula, but the finer-not-coarser reasoning is the
contract). g2-coding Q0-Q3 re-confirmation expected to agree; delegation would
save little on a slice this entangled.

## §9 Risks, Rollout, Rollback

| Risk | Trigger | Blast radius | Gate | Rollback |
|---|---|---|---|---|
| 039 fails on unmodeled prod data | deploy apply | deploy blocked at 039 | T6 models free-text/orphan/cross-tenant/shape-invalid classes | fix-forward 040 (policy: no renames) |
| Old worker writes free-text reason AFTER 039 applied | active crawl spanning deploy | swallowed finalize failure (fail-open) | **Deploy-order requirement (PR runbook): apply 039 + restart worker together while crawler is idle — the standing BLOCK disposition already forbids crawler runs until the train completes; verify no active run before apply** | stop worker; re-run crawl after full deploy |
| New code before 039 (reversed order) | operator applies code w/o migration | INSERT with unknown column → crawl fails closed at first acceptance (loud, not silent) | same runbook ordering; repo policy "additive migrations before matching code" | apply 039 |
| Old-key accepted rows spanning deploy | run in flight across deploy | second-row under new key + stale open row | forbidden by the same idle-window requirement; residual stale rows collapse via existing worker-exit reconciliation | F5 reconciliation (chartered) |
| Cross-keyword ledger rows | same project, 2 keywords | by design → F4 duplicate_in_run | FN1 Post documents | n/a |
| Conflict noise via R11 ERROR logs | latent replay-divergence bug | log noise only (fail-open) | T19 pins the distinct event; F4 escalates | revert |
| SQLite lacks FK enforcement | bootstrap-schema tests | test-blindness to referential bugs ONLY in unit tier | PG suite runs locally (binaries verified) and is the integrity oracle; divergence documented | n/a |
| Evidence loss in repair | 039 apply on real rows | orphan-run rows deleted | counts recorded at apply (runbook); all reason/project displacements preserved into terminal_detail; table is 3 days old, BLOCK in force, prod rows ≈ 0 | fix-forward |

No feature flag (Codex 4 dispositioned): the schema constraints and identity are
structural prerequisites for F4; a flag would fork the key-space. The enforced
idle window (BLOCK disposition + runbook order) is the compatibility protocol —
appropriate for this single-operator fleet; a multi-writer fleet would need a
phased dual-read approach that is out of scope here.

## §10 Do-Not-Touch List

- `apps/worker/src/egp_worker/browser_discovery.py` — scan-dedup semantics and
  callback payload are product behavior; the callback already carries what F8
  needs (verified :687-696)
- `apps/api/src/egp_api/services/discovery_worker_dispatcher.py` — EXCEPT the
  four reason literals + one import named in F9; no control-flow, retry, or
  reconciliation-path change (F5/F7 territory)
- `apps/worker/src/egp_worker/agent_runtime.py`, `apps/worker/src/egp_worker/main.py`
- `packages/db/src/migrations/001..038_*.sql` + historical duplicates
- `reconcile_open_candidates` semantics beyond the vocabulary guard (F5)
- `get_run_candidate_summary` (F4)
- run-outcome computation in `discover.py` (~L780-870) (F4)
- `packages/db/src/egp_db/repositories/run_repo.py`, `project_schema.py`
  (mirror parity for parent uniques deliberately NOT added — 034 precedent)
- generated web contracts / `apps/web/**`
- Acceptance-test assertions once locked by this v3 reconciliation (T1-T19)

## §11 Exact Gates And Formal Check

- Reconciliation proof: existing implementation behavior was already RED-proven
  in the historical Coding Log. New test-only tightening uses a one-behavior
  mutation of 039's repair vocabulary: the strengthened T15 must fail when one
  repair-list member is removed and pass after exact restoration.
- Scoped GREEN: the same test, then candidate accounting, candidate migration integrity, PostgreSQL dialect, worker live discovery, worker browser discovery, and affected dispatcher tests.
- Migration: `./.venv/bin/python scripts/check_migration_manifest.py`; real-PostgreSQL tests must report no skips.
- Static/full: `./.venv/bin/python -m ruff check apps/ packages/ tests/ scripts/`; `./.venv/bin/python -m ruff format --check apps/ packages/ tests/ scripts/`; `./.venv/bin/python -m compileall apps packages`; `./.venv/bin/python -m pytest tests/ apps/ packages/ -q`.
- Stability: run the affected F6 scope three consecutive times on the primary.
- g2 check phase: independent non-DeepSeek QCHECK, then the installed formal `g-check`, disposition every finding, and rerun both after material remediation.
- Delivery: one conventional commit and one PR to `main`; required checks must pass before the user-authorized admin merge. Fast-forward local `main`, assert local `main == origin/main == merge SHA`, and rerun the exact-SHA post-merge subset.
- Rollback: before merge, revert the feature commit. After 039 is applied, never edit it; stop writers and use a fix-forward `040+` migration. The canary remains BLOCKED pending F4/F5/F7/F8.

### Migration 039 idle-window preflight and evidence

Run only against the authorized target while crawler writers are stopped and
no crawl run is active. Capture command output in the deployment evidence
record; never paste credentials into logs or the PR.

1. Create and checksum a target backup using the operator's protected
   `DATABASE_URL`: `pg_dump --format=custom --file="$BACKUP_PATH" "$DATABASE_URL"`
   followed by `shasum -a 256 "$BACKUP_PATH"`.
2. Record pre-migration repair counts in one read-only transaction:
   - orphan/cross-tenant run rows: `NOT EXISTS` tenant-matched `crawl_runs`;
   - orphan/cross-tenant non-null project rows: `NOT EXISTS` tenant-matched `projects`;
   - terminal reasons outside the 16-value vocabulary;
   - dropped/failed/unknown rows with NULL reason;
   - persisted rows with NULL project;
   - accepted/persisted rows with non-null reason;
   - accepted/dropped/failed/unknown rows with non-null project.
3. Record `SELECT count(*) FROM crawl_runs WHERE status IN ('queued','running')`
   and require zero before apply.
4. Apply through `egp_db.migration_runner`; record the exact application SHA,
   `schema_migrations.filename = '039_candidate_attempt_integrity.sql'`, and
   the recorded checksum from `manifest.sha256`.
5. Rerun the seven counts: all constraint-violation categories must be zero;
   the survivor delta must equal the recorded orphan/cross-tenant run count.
6. Restart only the matching API/worker SHA, run the migration/focused health
   checks, and retain the backup until the rollback window closes. Any count
   mismatch or active run fails closed: stop and investigate; do not apply.

## §12 Baseline And Protected State

- Baseline: `4173dc4431ceb2703cab015b01d2865954fc8297`; branch `feat/canary-03-f6-candidate-integrity`; `origin/main` matched at the 2026-08-13 refresh.
- The pre-existing dirty worktree was archived before v3 edits at `/private/tmp/egp-f6-closeout.ID1Dyw` with binary diffs, all untracked files, metadata, and SHA-256 checksums.
- `test.sqlite3` is an untracked generated artifact, excluded from the PR and preserved only in the closeout archive.
- Migrations `001` through `038`, the primary checkout's dirty files, Git state, Coding Logs outside this F6 pair, and every file outside F1-F10 plus the named F6 tests are protected.
- The primary audits the complete changed-file set against this baseline before commit and again before worktree removal.

---

## Synthesis record — Codex adversarial pass (Phase 4)

Reviewer: `codex exec`, gpt-5.6-sol, xhigh, read-only, full repo access.
Output: `scratchpad/codex-plan-f6.md`. Verdict "No" on v1 → v2 above.
Dispositions (accepted findings are reflected in v2 sections):

1. **CRITICAL coverage gaps** — ACCEPTED in parts: marker/keyword identity →
   R7/FN1 revised (see 2); production conflict distinction → NEW R11/T19;
   workflow R5 test → NEW T17; nonexistent-project case → T3 extended; full
   shape matrix → T5 parametrized 20 tuples; typed reasons at producers → NEW
   F9 (dispatcher literals) + FN4/FN5 Python validator + R3(c,d). Propagation
   obligation was confirmed covered by Codex itself.
2. **CRITICAL identity decision** — PARTIALLY ACCEPTED. Accepted: keyword
   strip+casefold (mirrors discovery_authorization.py:73-96); organization_name
   joins the no-number identity (finer than dedupe — safe direction; closes the
   same-name/different-org class WITHIN the ledger). REJECTED: changing
   scan-dedup so such rows produce a second ledger row — that is product
   discovery behavior (which projects persist), out of this slice's charter and
   of the ledger's remit; rows skipped at scan are visible as `dedup_hits` scan
   stats, not ledger rows. Recorded as a known product-level limitation.
3. **CRITICAL conflict swallowed at call sites** — ACCEPTED: R11 + FN7 distinct
   except-branch + T19. Fail-open retained BY CHARTER (authority = F4);
   distinction is now observable, which is what MEDIUM 3 requires of THIS slice.
4. **HIGH deploy ordering / no flag** — PARTIALLY ACCEPTED: §9 gains the
   explicit idle-window + order requirement (039 before code, no active run;
   enforced by the standing BLOCK disposition + PR runbook). REJECTED: feature
   flag / compat protocol — forks the key-space, heavy for a single-operator
   fleet with an enforced idle window; documented as the accepted trade.
5. **HIGH missed files** — ACCEPTED: F10 (postgres-dialect test WOULD break —
   v1's "unchanged" claim was false), F9 (dispatcher literals). REJECTED:
   browser_discovery.py + its tests (see 2); run_repo/project_schema mirror
   parity (034 precedent verified: mirrors don't carry composite FKs or parent
   (tenant_id,id) uniques; PG suite is the oracle and runs locally).
6. **HIGH FN4 underspecified** — ACCEPTED: field-wise comparison contract +
   normalize_uuid_string on requested project_id + T8 parametrized incl. the
   equal-but-unnormalized non-conflict case (d).
7. **HIGH vacuous tests** — ACCEPTED: T5 full matrix; T8 per-field; T11 kept as
   repo-half with T17 covering the workflow half; T12/T16 golden vectors
   recomputed in-test via hashlib (constant-hash cheat fails); T13 rewritten for
   the v2 normalization partition; T14 asserts stored row + golden key (browser
   payload shape pinned by existing F2 tests); T6 gains fixtures (d) cross-tenant
   parent and (e) typed-but-shape-invalid.
8. **HIGH SQLite weaker than PG** — PARTIALLY ACCEPTED: divergence now explicit
   (§4 mirror note, §9 risk row) + local PG binaries verified so the oracle
   actually runs. REJECTED: mirror parity changes (precedent, blast radius — see 5).
9. **MEDIUM evidence destruction** — ACCEPTED: step-4 preserve-then-clear fix
   (the step-2/step-4 'worker_lost'-loss case is REAL and now fixed + T6(e));
   "idempotent-safe" wording corrected (runner-ledger single-shot); apply-time
   count recording added to runbook. REJECTED: quarantine table (permanent
   schema for a 3-day-old, BLOCK-guarded, ~zero-row ledger); ON DELETE CASCADE
   retained (034/crawl_tasks precedent; ledger rows meaningless without run).
10. **MEDIUM unclassified escape hatch** — ACCEPTED: Python-layer ValueError on
    non-members (R3c) makes silent collapse impossible without an enum+CHECK
    change; vocabulary extended with the 7 detail-terminal reasons so F4 cannot
    be forced into `unclassified` (FN2). `unclassified` itself retained for 039
    legacy normalization only (documented).
11. **LOW terminal_detail non-authoritative** — ACCEPTED AS DOCUMENTED (FN4).
12. **LOW fact-check** — all v1 factual anchors confirmed by the reviewer;
    no action.
