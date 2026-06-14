# WS1 QCHECK Task List — header-derived columns + canonical eligibility

For a **manual Codex review session** (read-only). Run Codex at repo root, paste the prompt
in §5, and work the checklist in §4. Record findings in §6. Fix CRITICAL/HIGH before commit.

## 1. How to use
- Start Codex read-only at `/Users/subhajlimanond/dev/egp`.
- Have it run `git diff` / `git status` and review ONLY the files in §2 (ignore unrelated modified coding-logs).
- Triage by severity; only CRITICAL/HIGH block the PR.

## 2. Scope (uncommitted WS1 changes)
```
apps/worker/src/egp_worker/browser_discovery.py    | 142 +++--   (resolver + rewiring + pagination)
apps/worker/src/egp_worker/browser_close_check.py  |  23 +++    (close-check matcher rewiring)
apps/worker/src/egp_worker/workflows/discover.py   |   4 +-     (persistence gate widened)
packages/crawler-core/.../invitation_rules.py      |  31 +++    (is_discoverable_stage_status)
packages/domain/.../project_ingest.py              |  13 +-     (persistence gate widened)
tests/phase1/test_worker_browser_discovery.py      | 144 ++     (7-col fixtures + new tests)
tests/phase1/test_invitation_rules.py              | NEW        (eligibility helper tests)
tests/phase1/test_projects_and_runs_api.py         |   5 +-     (gate message assert)
tests/operations/test_env_template.py              |   6 +-     (exclude diagnostic from scan)
scripts/diagnose_search_rows.py                    | NEW        (read-only diagnostic)
scripts/run_remote_crawl.sh                        |   4 +-     (diagnose subcommand)
```

## 3. Context (what changed and why)
Root cause (confirmed via live diagnostic): e-GP inserted a `หน่วยจัดซื้อ` column at index 2,
shifting every results-table column +1. Hard-coded `cells[4]`=status now reads budget →
`status_matches_target` always False → **0 eligible projects for every keyword**. Fix:
1. `resolve_results_columns(table)` derives indices from HEADER TEXT; raises `ResultsColumnsError`
   (loud) if a required column (status/project_name/view) is missing.
2. Rewired all positional cell reads (discovery + close-check) to header-derived indices.
3. New canonical `is_discoverable_stage_status` (invitation + pre-award) used by the row filter
   AND both persistence gates (replacing invitation-only `is_invitation_stage_status`).
4. Pagination off-by-one fix (no "next" click at `page_num >= max_pages`).

## 4. QCHECK task list (work each item)

### A. Column resolver correctness (browser_discovery.py)
- [ ] **A1** `resolve_results_columns` marker matching has NO cross-column false match. Verify
  `project_name` ("ชื่อโครงการ") does not match `สถานะโครงการ`, and `organization` ("หน่วยงาน")
  does not match `หน่วยจัดซื้อ` (and vice-versa). Confirm with the real 7-col header.
- [ ] **A2** Required-column set is right: status/project_name/view. Confirm a MISSING required
  header raises `ResultsColumnsError` (loud), and that optional columns (organization/
  purchasing_unit/budget) degrade gracefully (no KeyError downstream).
- [ ] **A3** `_extract_search_row` guard `len(cells) <= max(columns.values())` is correct for the
  resolved max index (no off-by-one; no IndexError on short rows).
- [ ] **A4** `_build_results_row_marker` `visible_signature` is stable/deterministic across pages
  (used for page-change detection + marker scoring). Confirm it doesn't crash when optional
  columns are absent.

### B. Eligibility semantics (crawler-core invitation_rules.py)
- [ ] **B1** `is_discoverable_stage_status` INCLUDES: หนังสือเชิญชวน/ประกาศเชิญชวน, จัดทำ TOR,
  ร่างเอกสารประกวดราคา, ประชาพิจารณ์, ราคากลาง.
- [ ] **B2** It EXCLUDES every post-award/cancel status — critically must NOT match
  `จัดทำสัญญา/บริหารสัญญา`, `อนุมัติสั่งซื้อสั่งจ้างและประกาศผู้ชนะการเสนอราคา`, `ยกเลิกโครงการ`,
  `-`, `""`, `None`. (Watch the "จัดทำ" prefix: must require "TOR", not match "จัดทำสัญญา"; and
  "ราคากลาง" must not match "เสนอราคา".)
- [ ] **B3** Whitespace/casefold handling is correct ("จัดทำ TOR" with a space, latin TOR token).

### C. Gate widening / lifecycle (discover.py, project_ingest.py)
- [ ] **C1** BOTH persistence gates now use `is_discoverable_stage_status` (row filter + worker gate
  + domain gate are CONSISTENT — no path discovers a row it later rejects).
- [ ] **C2** Pre-award projects (จัดทำ TOR / ราคากลาง) get a sane `project_state` (method-inferred
  OPEN_INVITATION/OPEN_CONSULTING) with no crash. Note any state-mapping imprecision as a
  follow-up (NOT a blocker) — confirm it doesn't break downstream lifecycle/backfill selection.
- [ ] **C3** The domain gate's raised message changed; confirm no other caller/test depends on the
  old string.

### D. Missed positional reads / regressions
- [ ] **D1** Grep the discovery + close-check paths for ANY remaining `cells[<int>]` positional read
  that should be header-derived (e.g. `_open_project_from_results_cell` call sites, document
  collection, `get_results_page_marker`). Confirm `get_results_page_marker`'s `cells[:5]` is an
  intentional layout-agnostic page-signature (OK) and not a status/name read.
- [ ] **D2** `_resolve_results_row_index` and `_build_candidate_row_snapshot` resolve columns
  before use and handle table-absent / ResultsColumnsError gracefully (return None / []).
- [ ] **D3** `status_matches_target` (old invitation-only compound matcher) — confirm it's either
  still legitimately used (document-collection invitation-row detection) or not left dangling/dead.
- [ ] **D4** Pagination off-by-one: with `max_pages=N`, exactly N pages are scanned and NO `next`
  click happens on page N. Confirm the guard is only in the discovery loop, not the close-check
  loop (different semantics).

### E. Tests
- [ ] **E1** The 7-col fixtures (`_results_headers`/`_results_row`) match the REAL e-GP layout
  (status@5, name@3, view@6, หน่วยงาน@1, หน่วยจัดซื้อ@2, budget@4).
- [ ] **E2** New tests exist for: resolver mapping, fail-loud on missing header, shifted-layout
  eligibility regression, pagination off-by-one, and the eligibility-status matrix.
- [ ] **E3** No test silently encodes the OLD layout (no remaining cells[2]=name / cells[4]=status).
- [ ] **E4** `test_env_template` exclusion of `diagnose_search_rows.py` is justified (dev tool, not
  runtime surface) and consistent with the existing `egp_crawler.py` exclusion.

### F. Diagnostic + script (lower priority)
- [ ] **F1** `scripts/diagnose_search_rows.py` is read-only (no DB writes, no doc downloads) and the
  `--attach` path won't kill a running keep-warm Chrome.
- [ ] **F2** `run_remote_crawl.sh diagnose` reuses the guard + validated env; no secret leakage.

## 5. Ready-to-paste Codex prompt
```
Read-only review of the uncommitted WS1 changes (run `git diff`/`git status`). Scope = the files in
section 2 of "coding-logs/2026-06-14-21-39-33 WS1 QCHECK Tasks (header-derived-columns).md"
(ignore unrelated modified coding-logs). Work the checklist in section 4 of that file. Report only
CRITICAL and HIGH findings with severity + file:line + the issue. Pay special attention to A1, B2,
C1/C2, D1, D3. Do NOT modify any files.
```

## 6. Findings (fill in)
- CRITICAL: _none yet_
- HIGH: _none yet_
- MEDIUM: _none yet_
- LOW: _none yet_

## 7. Pre-recorded local verification (already green before this QCHECK)
- `pytest tests/phase1 tests/phase2` → 516 passed.
- `pytest tests/phase1/test_worker_browser_discovery.py tests/phase1/test_invitation_rules.py tests/phase1/test_projects_and_runs_api.py` → 92 passed × 3 consecutive runs (no flakiness).
- `ruff check apps/ packages/` → All checks passed.
- Wiring: `is_discoverable_stage_status`, `resolve_results_columns`, `ResultsColumnsError` all have non-test importers.
- KNOWN PRE-EXISTING (NOT WS1, unrelated): `test_env_template` still flags 2 config.py warmup vars
  missing from the protected `deploy/.env.production.example`; `test_observability_stack` dashboard
  drift. Both predate WS1 and need protected-file edits — decide separately.
```
