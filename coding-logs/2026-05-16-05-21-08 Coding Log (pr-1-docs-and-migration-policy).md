# PR 1 — Refresh docs and AGENTS; document migration policy

## Plan Draft A

### Overview
Refresh only the guidance that is now demonstrably stale, then add one dedicated migration-policy document so future database work has a single canonical rule set. Keep this PR docs-only: no renames of historical migrations, no migration-runner behavior changes, and no runtime behavior changes.

### Files to Change
- `packages/AGENTS.md` — replace outdated scaffold/maturity descriptions with the current package reality.
- `apps/doc-processor/AGENTS.md` — describe the working processor package instead of a scaffold-only future service.
- `packages/db/AGENTS.md` — link to the migration policy and clarify future numbering rules.
- `AGENTS.md` — point contributors to the migration policy from the repo index.
- `CLAUDE.md` — replace stale sequential-only migration examples with the actual forward-looking rule.
- `docs/MIGRATION_POLICY.md` — new canonical policy covering unique future prefixes and historical duplicate handling.

### Implementation Steps
1. Inspect the current docs and migration directory to anchor every wording change in checked-in reality.
2. Add the new migration-policy doc first so the remaining docs can link to one source of truth.
3. Update `packages/AGENTS.md` to reflect that `crawler-core`, `document-classifier`, and `notification-core` now contain real modules.
4. Update `apps/doc-processor/AGENTS.md` to describe the existing CLI/facade and the split between app orchestration and shared classifier logic.
5. Update root/database guidance (`AGENTS.md`, `packages/db/AGENTS.md`, `CLAUDE.md`) so contributors can discover the policy and understand why old duplicate prefixes remain untouched.
6. Run focused documentation validation and a self-review before submission.

### Test Coverage
- No runtime tests added: documentation-only change.
- `rg`/link sanity pass — confirm stale scaffold wording is gone and new policy references resolve.
- migration inventory check — confirm historical duplicate prefixes remain documented as historical facts.

### Decision Completeness
- **Goal:** make contributor guidance match the current repo and establish an unambiguous migration numbering rule going forward.
- **Non-goals:** renaming existing migrations, changing migration-runner code, adding schema changes, or broad documentation rewrites outside the identified stale areas.
- **Success criteria:**
  - docs no longer claim implemented packages are scaffolds;
  - doc-processor guidance matches the actual checked-in processor modules;
  - future migrations have one documented policy;
  - historical duplicate prefixes are explicitly acknowledged and left unchanged.
- **Public interfaces:** docs only; no API, env-var, CLI, or schema changes.
- **Edge cases / failure modes:**
  - contributors may assume duplicate prefixes should be renumbered — policy says preserve applied historical filenames;
  - contributors may choose the next apparently missing number instead of a globally unique one — policy says use the next unused prefix after the current max;
  - docs may drift again if multiple places explain numbering differently — dedicated policy doc becomes the canonical source.
- **Rollout & monitoring:** no rollout needed; watch future migration PRs for compliance with the policy.
- **Acceptance checks:** `rg` for stale wording, file/link spot checks, migration filename inventory review.

### Dependencies
- Current migration inventory under `packages/db/src/migrations/`.
- Existing checked-in implementations under `packages/crawler-core`, `packages/document-classifier`, `packages/notification-core`, and `apps/doc-processor`.

### Validation
- Re-read touched docs in context.
- Confirm every new relative link resolves.
- Confirm no historical migration file names were changed.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| `docs/MIGRATION_POLICY.md` | Contributor docs lookup | Linked from `AGENTS.md`, `packages/db/AGENTS.md`, and `CLAUDE.md` | N/A |

## Plan Draft B

### Overview
Make the smallest possible cleanup: update the obviously stale AGENTS wording and add a short migration section directly inside `packages/db/AGENTS.md`, without creating a new standalone document. This reduces file count but leaves long-term migration guidance less discoverable outside the database package.

### Files to Change
- `packages/AGENTS.md`
- `apps/doc-processor/AGENTS.md`
- `packages/db/AGENTS.md`
- optionally `CLAUDE.md`

### Implementation Steps
1. Replace stale package/doc-processor descriptions in place.
2. Add a concise future-numbering note under `packages/db/AGENTS.md`.
3. Update `CLAUDE.md` only if its examples remain misleading after the local db guidance changes.
4. Run focused documentation validation.

### Test Coverage
- No runtime tests added: documentation-only change.
- Spot-check stale wording and migration examples.

### Decision Completeness
- **Goal:** fix the minimum misleading guidance.
- **Non-goals:** broader doc discoverability or a new canonical policy file.
- **Success criteria:** no known false statements remain in the touched AGENTS files.
- **Public interfaces:** docs only.
- **Edge cases / failure modes:** contributors who read root docs but not `packages/db/AGENTS.md` may still miss the migration policy.
- **Rollout & monitoring:** none.
- **Acceptance checks:** targeted `rg` plus manual reread.

### Dependencies
- Same current repo inspection as Draft A.

### Validation
- Manual spot-check of touched files.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| inline migration guidance | `packages/db/AGENTS.md` readers | N/A | N/A |

## Comparative Analysis & Synthesis

### Strengths
- Draft A gives the migration policy a durable home and makes it discoverable from every place contributors are likely to start.
- Draft B is smaller and faster, with fewer files touched.

### Gaps
- Draft A is slightly more editorial work than strictly necessary.
- Draft B keeps the important policy too local and risks future drift between root docs and database docs.

### Trade-offs
- For a repo with already-divergent docs, the extra standalone file in Draft A is worth the small increase in diff size because it reduces future ambiguity.
- Because historical duplicate prefixes already exist, a canonical statement matters more than shaving one file from the PR.

### Compliance Check
- Both plans respect the docs-only scope and avoid renaming applied migrations.
- Draft A better satisfies the repo rule to keep docs and schema guidance consistent across packages.

## Unified Execution Plan

### Overview
Use Draft A. Create one canonical migration-policy document, then align the surrounding guidance so the repo describes what exists today rather than what existed at scaffold time. Keep the PR intentionally narrow and behavior-free.

### Files to Change
- `docs/MIGRATION_POLICY.md` — canonical future policy and historical duplicate explanation.
- `packages/AGENTS.md` — current package maturity and examples.
- `apps/doc-processor/AGENTS.md` — current app role, entrypoint, and live modules.
- `packages/db/AGENTS.md` — point to the policy and summarize the future numbering rule.
- `AGENTS.md` — expose the policy in the root JIT index.
- `CLAUDE.md` — replace stale migration examples with policy-consistent guidance.

### Implementation Steps
1. Add `docs/MIGRATION_POLICY.md` with:
   - current runner behavior (filename-sorted, filename-recorded),
   - historical duplicate prefixes (`002_*`, `008_*`) left as-is,
   - future rule: use the next unused zero-padded prefix after the current maximum,
   - explicit do/don't guidance for contributors.
2. Update package maturity wording:
   - `packages/AGENTS.md` should name the real responsibilities now present in `crawler-core`, `document-classifier`, and `notification-core`.
3. Update doc-processor wording:
   - describe `src/main.py` as a thin CLI entrypoint,
   - name `egp_doc_processor.processor.DocumentProcessor` and current shared-package collaborators,
   - keep the no-app-local-tests caveat accurate.
4. Update root/database guidance:
   - link the new policy from `AGENTS.md` and `packages/db/AGENTS.md`,
   - update `CLAUDE.md` examples so they no longer imply the repo has perfectly unique historical numbering.
5. Run documentation validation:
   - targeted `rg` searches for stale wording,
   - link/path spot checks,
   - migration inventory check proving no historical rename happened.
6. Self-review the branch, append implementation notes to this log, then submit.

### Test Coverage
- `test_docs_claims_match_repo_state` (manual validation) — stale scaffold claims removed.
- `test_migration_policy_matches_inventory` (manual validation) — duplicate historical prefixes named correctly.
- `test_new_doc_links_resolve` (manual validation) — new references point to real files.

### Decision Completeness
- **Goal:** align docs with reality and lock future migration numbering policy.
- **Non-goals:** code changes, schema changes, migration renames, migration-runner changes.
- **Success criteria:**
  - every touched claim is accurate against current files;
  - contributors can discover the policy from root and db docs;
  - future numbering guidance is explicit and singular;
  - existing duplicate prefixes remain unchanged and explained.
- **Public interfaces:** documentation only.
- **Edge cases / failure modes:**
  - **duplicate historical prefix confusion:** preserve applied names; fail closed on renumbering by policy.
  - **next-number collision:** future authors must choose the next unused prefix after the current maximum.
  - **documentation drift:** one canonical policy doc plus linked summaries reduces split-brain guidance.
- **Rollout & monitoring:** immediate after merge; watch subsequent migration PRs and code reviews for adherence.
- **Acceptance checks:**
  - `rg -n "still scaffolds|Only `db` and `shared-types` have meaningful checked-in content today|entrypoint is still scaffold-only" ...` returns no stale matches in touched docs;
  - `find packages/db/src/migrations ...` still shows both historical duplicate pairs;
  - every new relative link opens to an existing file.

### Dependencies
- Existing current repo state and migration inventory only.

### Validation
- Manual readback of touched files.
- Exact-string checks for removed stale claims.
- Filename inventory review for migration history.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| `docs/MIGRATION_POLICY.md` | contributors reading repo/database guidance | linked from root `AGENTS.md`, `packages/db/AGENTS.md`, and `CLAUDE.md` | N/A |


## Implementation Summary (2026-05-16 05:22:47)

### Goal
Refresh contributor-facing docs for PR 1 and add a canonical migration numbering policy.

### What Changed
- `docs/MIGRATION_POLICY.md` — added the canonical future-numbering rule, documented the filename-based migration-runner behavior, and called out the historical duplicate `002_*` / `008_*` prefixes that must remain unchanged.
- `packages/AGENTS.md` — replaced scaffold-era package descriptions with the current shared-package responsibilities and updated the touch-point list.
- `apps/doc-processor/AGENTS.md` — replaced scaffold-only wording with the current CLI/facade structure and live module references.
- `packages/db/AGENTS.md` — linked the new migration policy and summarized the forward-looking numbering rule plus historical duplicate-prefix caveat.
- `AGENTS.md` — exposed the migration policy from the root JIT index.
- `CLAUDE.md` — corrected stale package paths/responsibilities and aligned migration guidance with the new policy.

### TDD Evidence
- No RED run was produced because this change is documentation-only and does not alter executable behavior.
- Focused validation command (GREEN): `rg -n 'still scaffolds|Only `db` and `shared-types` have meaningful checked-in content today|entrypoint is still scaffold-only|numbered sequentially' AGENTS.md packages/AGENTS.md apps/doc-processor/AGENTS.md packages/db/AGENTS.md CLAUDE.md docs/MIGRATION_POLICY.md || true`
- Focused validation command (GREEN): `find packages/db/src/migrations -maxdepth 1 -type f -name '*.sql' | sort`

### Tests / Checks Run
- Exact-string stale-claim search: no matches remained in the touched docs.
- Migration inventory review: confirmed the historical duplicate prefixes remain `002_*` and `008_*`.
- Relative-link spot checks via a small Python existence check: all newly linked targets exist.

### Wiring Verification Evidence
- `docs/MIGRATION_POLICY.md` is linked from `AGENTS.md`, `packages/db/AGENTS.md`, and `CLAUDE.md` so contributors can discover the canonical policy from root and database guidance.

### Behavior / Risk Notes
- Runtime behavior is unchanged.
- The main risk addressed is contributor confusion around historical duplicate prefixes; the docs now make the fail-closed policy explicit: do not rename applied files, and use the next globally unused prefix for future migrations.

### Follow-ups / Known Gaps
- This PR intentionally does not attempt a repo-wide documentation rewrite beyond the stale claims needed for PR 1.


## Review (2026-05-16 05:23:28) - staged working tree

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: staged working tree for PR 1 docs-only change
- Commands Run: `git diff --staged --name-only`, `git diff --staged --stat`, targeted `git diff --staged -- <paths>`, exact-string stale-claim search, migration inventory check, link-target existence check

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
- Assumed the desired policy is forward-looking only: preserve already-applied historical filenames and enforce unique prefixes only for new migrations.

### Recommended Tests / Validation
- Re-run the stale-claim search and migration inventory check after any follow-up edits.
- Manually inspect the rendered Markdown links in GitHub before merge.

### Rollout Notes
- Documentation-only change; no runtime rollout or backout steps required.
