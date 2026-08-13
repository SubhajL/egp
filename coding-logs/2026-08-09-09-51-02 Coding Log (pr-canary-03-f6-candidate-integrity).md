# Coding Log: PR-CANARY-03 F6 + candidate identity — Candidate-Attempt Integrity

Started: 2026-08-09 09:51:02 +0700
Branch: feat/canary-03-f6-candidate-integrity (from main 4173dc44)

## Goal

Implement slice F6 + the candidate-identity slice per the canonical table in
`coding-logs/2026-08-09-09-45-52 Coding Log (pr-canary-03-remediation-reconciliation).md`:

- F6 (07:48:44 HIGH 6): migration `039` — composite tenant foreign keys with the
  required unique parent keys, typed `terminal_reason` vocabulary, status/reason/
  project CHECK combinations, and a typed conflict on contradictory terminal
  rewrite (F1 log deferral).
- identity (07:48:44 MEDIUM 3 + F2 DREP §9-D): content-based `candidate_key`
  (project_number/project_name identity mirroring the run dedupe key), row-marker/
  project-number propagation at acceptance, no fabricated `0,0` coordinates,
  identical-replay-returns-record vs typed-conflict semantics.

DREP: `coding-logs/2026-08-09-09-51-02 DREP (pr-canary-03-f6-candidate-integrity).md`
(v2 — post Codex adversarial plan review, gpt-5.6-sol xhigh; all 12 findings
dispositioned in the DREP's Synthesis record.)

## Stop line / delegation decision

**Q0 fired → no delegation; Claude implemented everything.** Triggers: the
slice ships a migration (never-delegate #4) and DB-enforced tenant-isolation
constraints (never-delegate #3). Recorded per g2-coding: no stop line applies;
Phase 2c-ter full-TDD discipline used instead (test → RED → implement → GREEN
per unit). Delegate fix rounds: n/a. Delegate tokens: 0.

## TDD record (RED causes proven before each implementation unit)

- S1 (T1-T6, T15): module ImportError (`CandidateTerminalReason` absent) →
  enum landed → T15 FileNotFoundError (039 absent) → 039 + manifest landed →
  26/26 green. Two harness defects found at RED-run time (psycopg
  InFailedSqlTransaction after expected violations) fixed with explicit
  rollbacks — harness fixes, not contract changes.
- F10 (dialect-test fixture): predicted breakage CONFIRMED (random run_id
  violates dca_tenant_run_fkey after 039) → fixture seeds a real run+project →
  2/2 green. v1-DREP's "unchanged" claim was wrong; caught by Codex (finding 5).
- S2 (T7-T11 + L67 semantic rewrite): ImportError
  (`CandidateTerminalConflictError` absent) → repo implementation → 15/15.
- S3 (T12-T14, T16, T17, T19): TypeError (old 4-arg key signature) /
  raw-exception-reason asserts / missing distinct conflict event → key +
  workflow implementation → 21/21 selected.
- Mutation evidence (2c-bis) for the one layer with no dedicated RED — the
  SQLAlchemy mirror CHECKs: raw-SQL probe proved SQLite enforcement
  (IntegrityError both for vocab and shape), then pinned durably as
  `test_sqlite_mirror_enforces_vocab_and_shape_checks`.

## Gates (Claude-run)

- Affected suites: 111 passed (accounting 16, integrity-migration 26 on real
  PostgreSQL via TempPostgresCluster, dialect 2, live-discovery full file).
- 3× flakiness on accounting + live-discovery: 83/83 ×3, stable.
- Ruff repo-wide: clean. `ruff format` applied only to files whose 4173dc44
  baseline was format-clean (candidate_key.py, enums.py, new test file);
  base-dirty files (candidate_attempt_repo.py, discover.py) intentionally NOT
  blanket-reformatted.
- compileall: clean.
- Wiring: every new export has a non-test import AND a runtime call site
  (CandidateTerminalReason → discover.py:722 + dispatcher:1140/1187/…;
  CandidateTerminalConflictError → discover.py:695/:725 except branches;
  content key → both acceptance call sites; conflict-log helper → 2 call sites).
- Full repository suite: **1561 passed, 2 failed, 2 skipped** (3m29s). The two
  failures are both `tests/operations/test_env_template.py`
  (`test_env_template_tracks_runtime_egp_vars`,
  `test_env_template_covers_all_compose_required_vars`) and REPRODUCE
  IDENTICALLY on the pristine 4173dc44 primary checkout → pre-existing,
  unrelated to this slice.

## Incident note

One verification helper command included a leftover `git stash push` inside a
loop, which stashed the uncommitted slice mid-implementation. Recovered
completely with `git stash pop` (stash@{0}; the 11 historical stashes
untouched); all suites re-run green after restore. No content lost (untracked
new files were never stashed).

## Lifecycle reconciliation (2026-08-13 10:00 +0700)

### Goal and baseline

- Resumed the pre-existing worktree `/Users/subhajlimanond/dev/egp-canary03`
  on `feat/canary-03-f6-candidate-integrity` at
  `4173dc4431ceb2703cab015b01d2865954fc8297`; refreshed `origin/main` matched.
- Preserved the complete pre-edit state at
  `/private/tmp/egp-f6-closeout.ID1Dyw`: porcelain-v2 status, binary tracked
  diff, staged diff, all untracked files, metadata, and `SHA256SUMS`.
- RepoPrompt was bound to the exact worktree and used for a focused source,
  schema, runtime-consumer, and test reconciliation.

### g2 planning disposition

- Reconciled the DREP to v3: the implemented identity is compact-JSON
  `egp-candidate-key.v2`, using project number when present and otherwise the
  visible name/organization/budget/status signature. `row_marker` is canonical
  JSON stored as opaque TEXT; the enum has 16 values; the full shape matrix has
  5 valid and 15 invalid tuples; T16-T19 live under worker-live tests.
- Rejected an invented direct-path budget requirement. Direct/materialized
  payloads contract project number, organization, and source status but do not
  carry the browser row's formatted `budget_text`; no production change was
  made for a fictitious parity contract.
- Added the exact idle-window backup, seven-class pre-count, zero-active-run,
  apply, post-count, checksum, and fail-closed evidence procedure for migration
  039. Deployment remains blocked behind the canonical F4/F5/F7/F8 sequence.
- Q0-Q3: all F6 slices are PRIMARY at Q1 because they contain migration,
  tenant-integrity, concurrency, and cross-package identity contracts. No
  DeepSeek allowlist exists, no repository content was externally delegated,
  and the external route/doctor was not exercised. Pilot provider/model/tokens,
  cost, latency, proxy failures, scope violations, and delegate rework are all
  n/a/zero for this primary-owned slice.
- Independent read-only Terra challenge found no new critical source defect;
  accepted the DREP drift and destructive-migration runbook findings. Retained
  raw `terminal_detail` confidentiality/retention as explicit F8 debt and the
  run-authority/reconciliation gaps as F4/F5 blockers.

### Reconciliation test proof

- File changed: `tests/phase1/test_candidate_integrity_migration.py`; added an
  assertion that migration 039's repair vocabulary exactly equals its own
  CHECK vocabulary without freezing future migrations to applied history.
- Initial GREEN (behavior pre-existed):
  `./.venv/bin/python -m pytest tests/phase1/test_candidate_integrity_migration.py::test_terminal_reason_vocabulary_drift_guard -q`
  -> `1 passed`.
- Mutation RED: temporarily removed `detail_unknown` from only 039's repair
  list; the same command failed at the new equality assertion with
  `check-only=['detail_unknown']` for the expected reason.
- Exact restoration GREEN: restored `detail_unknown`; the same command ->
  `1 passed`. Restored migration SHA-256
  `e38d94aad59b9166340425d2bcbad02d2670cb985ba02d9a0ebaf5b52dbed9b2`,
  equal to `manifest.sha256`.
- Non-behavioral source change: corrected the direct-path identity comment in
  `apps/worker/src/egp_worker/workflows/discover.py`; runtime behavior unchanged.

### Wiring evidence

| Component | Non-test caller | Registration/config | Schema/contract |
|---|---|---|---|
| migration 039 | `egp_db.migration_runner.apply_migrations()` | filename order + `manifest.sha256` | `discovery_candidate_attempts`, `crawl_runs`, `projects` |
| candidate repository | `egp_worker.main.run_worker_job()` and `agent_runtime._build_browser_executor()` | repository factory injected into `run_discover_workflow()` | 039 columns/CHECKs/composite FKs |
| content key/provenance | `run_discover_workflow()` direct path and `_record_live_candidate()` callback | `browser_discovery._collect_keyword_projects()` callback | run-local candidate uniqueness |
| terminal conflict event | both persistence success/failure finalizers in `run_discover_workflow()` | `_log_candidate_terminal_conflict()` | existing/requested triples |
| dispatcher reconciliation reasons | `SubprocessDiscoveryDispatcher.dispatch_cancellable()` and termination flow | shared `CandidateTerminalReason` import | closed SQL/Python vocabulary |

Fail semantics: candidate acceptance and DB-constraint failures fail closed;
terminal finalization conflicts are distinctly logged but remain fail-open until
F4 owns run authority. Raw exception detail is diagnostic debt for F8 and must
not be broadly exposed.

## Independent QCHECK (2026-08-13 10:55 +0700)

- Reviewer: `terra_support`, read-only, non-DeepSeek, exact working-tree diff.
- Verdict: no blocking F6 findings.
- Confirmed structured JSON identity, intentional live/direct input asymmetry,
  missing/identical/conflicting finalize semantics, both structured conflict
  event paths, real-PostgreSQL tenant/shape constraints, and the F4/F5/F7/F8
  scope boundary.
- Residual rollout cautions: migration 039 deletion requires the documented
  backup/pre-count/idle/apply/post-count evidence; `terminal_detail` remains
  non-user-facing F8 redaction/retention debt.
- The reviewer reused primary gate evidence and did not independently rerun
  tests. Formal disposition stays with the primary.

## Review (2026-08-13 10:56:25 +0700) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp-canary03`
- Branch: `feat/canary-03-f6-candidate-integrity`
- Scope: staged 16-file working tree against `4173dc4431ceb2703cab015b01d2865954fc8297`
- Commands Run: `git status --short`; staged name/status/stat/check; targeted
  RepoPrompt source and wiring reads; migration checksum/manifest check;
  immutable-038 diff; `ruff check`; scoped format checks; `compileall`; affected
  pytest scope; full pytest; three affected repeats; exact baseline reproduction
  of the two unrelated operations failures.

### Findings
CRITICAL
- No findings.

HIGH
- No findings.

MEDIUM
- No findings.

LOW
- No findings.

### Open Questions / Assumptions
- Assumes the production migration is not applied until crawler writers are
  idle, the seven-class preflight counts and backup are recorded, and no active
  run crosses the schema/code boundary.
- F4/F5/F7/F8 remain explicit blockers to canary activation; this PR does not
  claim run authority, complete abnormal-path reconciliation, fault injection,
  or diagnostic redaction/retention closure.

### Recommended Tests / Validation
- Completed: affected scope `224 passed` including real PostgreSQL, then three
  consecutive repeats of `224 passed` each.
- Completed: `ruff check`, scoped no-new-format-debt verification, `compileall`,
  migration manifest verification, migration 038 immutability, and mutation
  proof for 039 repair/CHECK vocabulary equality.
- Full suite: `1565 passed, 2 skipped, 2 failed`; both failures are existing
  environment-template drift and reproduced identically on unchanged local
  `main` (`EGP_BROWSER_DIAGNOSTICS_DIR`, `EGP_RELEASE_SHA`). They are not waived
  as passes and are unrelated to F6.

### Rollout Notes
- Apply migration 039 only via the documented backup/pre-count/idle-window/
  post-count procedure, then restart the matching API/worker SHA.
- Before merge, rollback is commit reversion. After apply, migration 039 is
  immutable and rollback is a stopped-writer fix-forward `040+` migration.
- Keep `terminal_detail` non-user-facing; F8 owns durable redaction and
  retention. Keep canary activation blocked pending the canonical remaining
  F-series.

### Formal disposition

- `g-check`: PASS for F6 source/PR readiness; no product-code remediation
  required.
- Baseline repository gate remains red for the two independently reproduced
  environment-template failures. This does not alter the F6 source verdict but
  must remain visible in the PR and required-check handling.
