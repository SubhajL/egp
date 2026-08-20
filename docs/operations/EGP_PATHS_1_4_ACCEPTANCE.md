# EGP Paths 1-4 Acceptance Record

Date: 2026-08-20 (Asia/Bangkok)

Baseline source: `f1e8182cdabb07b8c890b5a2ad2d8f1672e0125a` (merged PR #220)

## Outcome summary

| Path | Outcome | Meaning |
|---|---|---|
| 1 - current-host F7 acceptance | Failed: target not deployed | The active native executor, Docker services, and target database predate the F7 release. No production fault was injected. |
| 2 - isolated exact-SHA staging | Accepted | Fresh PostgreSQL migration and F7 terminalization contracts passed at the exact baseline SHA without production access. |
| 3 - re-audit and selected remediation | Source/local gates accepted | Runtime images and trusted entrypoints now carry exact release provenance. Independent QCHECK and formal g-check are clean; deployment remains separately authorized. Broader architectural findings remain separately planned. |
| 4 - maintenance | Partially complete in this record | Protected artifacts and the retained F7 branch were classified conservatively. Dependency remediation is delivered separately. |

## Path 1: truthful current-host result

The current host cannot provide operational acceptance for PR #220:

- The active native discovery executor runs editable source from the pre-existing
  `egp-ops-main` worktree at `722b1e0ece9571bddc710c5dc69c9ac45a14c066`, not the target SHA.
- The running API container is an older local-development image without current readiness or
  release-provenance surfaces. The Docker discovery executor is stopped and also predates the
  target release.
- The connected target database records migrations only through 037. Candidate migrations 038
  and 039 are absent, so the F7 candidate-terminalization oracle cannot run there.
- Read-only diagnostics found 13 pending and claimable jobs, zero leased jobs, zero active
  correlated run/job pairs, zero active runs without a current lease, and zero stale
  metadata-less reservations. The persistent browser profile requires operator action.

Result: `PATH_1_FAILED_TARGET_NOT_DEPLOYED`. This is an environment/version finding, not a source
test failure. No service, database row, profile, lock, environment file, or deployment was changed.

## Path 2: isolated exact-SHA staging

An ephemeral PostgreSQL cluster was created from the exact baseline source and destroyed after
verification:

- All 41 migrations through 039 applied successfully.
- `tests/operations/test_f7_terminalization_postgres.py`: 9 passed, 1 skipped in the full module.
- The explicitly enabled real-PostgreSQL contract passed separately: 1 passed.
- Fresh-database invariants showed 41 recorded migrations, the candidate-attempt table present,
  zero active runs, and zero accepted candidates.

Result: `PATH_2_STAGING_ACCEPTED`. The production database and active crawler were not used.

## Path 3: re-audit and release provenance

The re-audit confirmed that the target database role is highly privileged and that tenant tables
do not currently use PostgreSQL row-level security. That is a separate security-hardening program:
role/grant design, credential rollout, additive constraints or policies, migration/backfill, and
production authorization must be planned together. This lifecycle did not mutate database roles,
grants, policies, credentials, or schemas.

The first decision-complete slice instead closed the immediate release-identity gap with trusted
build and runtime entrypoints:

- API and worker images embed the exact Git SHA in the OCI revision label and baked runtime env.
- Production and rollback builds use a wrapper that derives the exact clean checkout SHA
  immediately before Compose; the persistent env template cannot supply it. Local development uses
  an explicit local marker.
- The wrapper rejects ordinary or ignored executable inputs, runtime-source mounts, dirty tracked
  state, malformed revisions, and rollback trees missing the current five-service topology before
  invoking Compose.
- CI and image publishing pass the exact workflow commit SHA.
- Runtime smoke verifies both the image label and baked environment and rejects mismatches.
- The native remote-crawl runner derives the exact clean tracked checkout SHA, overrides stale
  env-file provenance, and fails closed on staged or unstaged tracked drift.

Primary verification includes 319 operations tests passed / 2 skipped and a full repository result
of 1,989 passed / 4 skipped, plus scoped Ruff, shell syntax, and diff checks. Exact-SHA API and
worker image builds, a passing runtime smoke, and a deliberate mismatch that failed closed were
completed before the final overlay/rollback hardening; the final trusted-wrapper image build/smoke
is repeated from the clean committed candidate before delivery. No image was published or
deployed.

## Path 4: conservative maintenance decisions

- The remote F7 branch is retained because its squash-merged head is not reachable from
  `origin/main` and still contains unique commits.
- The seven pre-existing dirty or untracked primary-checkout paths remain user-owned and were not
  modified, quoted, deleted, or moved.
- The pre-existing `egp-ops-main` worktree remains outside lifecycle cleanup scope.
- The lifecycle worktree is removed only after merge, exact-SHA local-main landing, and protected
  artifact re-verification.
- npm advisory remediation is intentionally separated so its lockfile-only change and frontend
  gates have an independent acceptance trail.

## Operational next step

Before any production F7 canary, deploy an immutable image built from the intended SHA, expose that
identity on every runtime role, apply migrations 038 and 039 through the normal governed release
path, and repeat the read-only preflight. Fault injection or agent-primary activation still requires
separate production authority.
