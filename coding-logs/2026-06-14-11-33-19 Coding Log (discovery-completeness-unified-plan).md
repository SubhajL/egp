# Coding Log: discovery-completeness-unified-plan (2026-06-14)

> **v2 (2026-06-14, post-diagnostic).** Root cause is now **CONFIRMED by live evidence**, not hypothesized.
> This supersedes v1's speculation (H1 short-form status / H2 column drift / "two bugs A+B" / diagnostic-first-to-decide).
> **It is ONE bug: results-table column drift (off-by-one).** Changelog at the bottom.

Incorporates THREE review bodies + live diagnostic evidence:
- **(A) Discovery-completeness** — senior team-lead system review (`coding-logs/2026-06-13-09-53-19 …`) + Claude analysis + **WS0 diagnostic run (2026-06-14)**.
- **(B) Document-capture / backfill** — the "B+" review of `#142`/`#143` + parser hardening (every item mapped, WS3/WS4).
- **(C) Shipped `crawl-batch-observability` PR** — zero-result keyword tasks, profile-create admission, log-path remap, UI summary. **Extended, not redone.**

---

## 1. CONFIRMED root cause — results-table column drift (off-by-one)

e-GP inserted a new **`หน่วยจัดซื้อ` (procuring unit)** column at position 2 of the search-results table, shifting every later column **+1**. The crawler hard-codes positional indices, so they are now all wrong. Current real layout (7 columns):

| idx | header | crawler currently treats it as | correct field |
|---|---|---|---|
| 0 | ลำดับ | row # | row # |
| 1 | หน่วยงาน | organization | organization |
| 2 | **หน่วยจัดซื้อ** (NEW) | **project name** ❌ | procuring unit |
| 3 | ชื่อโครงการ | budget ❌ | **project name** |
| 4 | วงเงินงบประมาณ (บาท) | **status** ❌ | **budget** |
| 5 | สถานะโครงการ | view-button ❌ | **status** |
| 6 | ดูข้อมูล | — | **view/action** |

`status_matches_target(cells[4])` compares the target status against a **budget number** → always False → **0 eligible for every keyword**. The matching logic is correct; it is pointed one column left.

### Live evidence (WS0 diagnostic, keyword `วิเคราะห์ข้อมูล`, 7 pages)
- e-GP `จำนวนโครงการที่พบ` = **761**; `find_results_table` matched the right table (10 rows/page); 70 rows scanned; **eligible = 0**.
- The status column (`cells[5]`) vocabulary: `จัดทำสัญญา/บริหารสัญญา`(45), `อนุมัติ…ประกาศผู้ชนะ`(13), **`หนังสือเชิญชวน/ประกาศเชิญชวน`(8)**, `จัดทำ TOR`(2), `ยกเลิกโครงการ`(1), `-`(1).
- All **5** user-flagged projects: `found_in_scan = True`, real status = exactly **`หนังสือเชิญชวน/ประกาศเชิญชวน`**. **8** invitation-stage projects existed on those pages; all were missed for this one reason.

### Proven scope of the bug
- **A/B confirmed:** legacy `egp_crawler.py` returns **0 eligible across all 12 keywords** — byte-identical to the web app. The web app is a **faithful port**, NOT a divergence. The fix belongs in the shared logic (the worker; `egp_crawler.py` is legacy/deprecated).
- The off-by-one also corrupts: project name (reads `หน่วยจัดซื้อ`), the view-click target (reads status text, not the action), budget, and the `SKIP_KEYWORDS` match field.
- v1's H1 (short-form status) was a red herring — the status *is* the exact compound. The only matching change needed is the **pre-award widening** (a product choice), not a fix to the invitation match.

**Meta-lesson:** never hard-code result columns — derive from headers; and a `found>0 && eligible==0` guard is the cheapest possible canary (it would have caught this on day one).

## 2. Locked decisions (product owner)
1. **Coverage = invitation + pre-award.** Include statuses: `หนังสือเชิญชวน/ประกาศเชิญชวน`, `จัดทำ TOR`, draft/`ประชาพิจารณ์`/`ร่างเอกสารประกวดราคา`, `ประกาศราคากลาง`/`ราคากลาง`. Exclude post-award: `จัดทำสัญญา/บริหารสัญญา`, `อนุมัติ…ประกาศผู้ชนะ`, `ยกเลิกโครงการ`, `-`.
2. **SKIP_KEYWORDS = keep as-is.** Note: the header-mapping fix incidentally makes it check the *real* `ชื่อโครงการ` (it was checking `หน่วยจัดซื้อ`). Validate this behavior change; do not alter the list.
3. **Production repair = one-time re-scan** after the fix.
4. **Retry horizon** for `no_documents` with unknown deadline = **30-day** daily-heartbeat cap.
5. **Diagnostic-first** — DONE (WS0).

## 3. Assets already built
- `scripts/diagnose_search_rows.py` — read-only diagnostic: dumps `egp_found`, all tables (+matched flag), per-row cells, header row, eligibility decision, known-missed lookup. (Found+fixed a `slots=True` dataclass default bug during use.)
- `scripts/run_remote_crawl.sh diagnose …` subcommand (guard + validated env).
- Captured fixture: `artifacts/diagnostics/search_rows_20260614-123156.json` (real header row + 70 rows) → seeds WS1 tests and the WS6 replay harness.

---

## 4. Workstreams

### WS0 — Diagnostic & fixtures — ✅ DONE
Built the diagnostic + runner subcommand; ran it; **confirmed column drift**; captured the fixture JSON. Output of §1 is the result.

### WS1 — Header-derived columns + canonical eligibility (P0 — THE fix)
1. **Header→index resolver** for the matched results table: map `สถานะโครงการ, ชื่อโครงการ, หน่วยงาน, หน่วยจัดซื้อ, วงเงินงบประมาณ, ดูข้อมูล` → indices. **Fail loud** (anomaly) if a required header is missing/renamed — never silently fall back to a guessed index.
2. **Rewire** `_extract_search_row`, `_build_results_row_marker`, the eligibility loop, the detail/view-click navigation, budget parse, project-number extraction, and the SKIP-keyword field to use resolved indices (kills the off-by-one everywhere).
3. **Canonical eligibility module** in `crawler-core`, shared by the row filter AND the persistence gate (replaces lone `TARGET_STATUS` + `is_invitation_stage_status`): accept the invitation + pre-award status set (decision 1); map status → `ProjectState`. **Sub-task:** enumerate the *full* e-GP status vocabulary (run the diagnostic across several keywords/pages) before finalizing the set, so no pre-award spelling is missed.
4. **Cross-announcement dedup + lifecycle** (new-coverage risk): a project may appear under multiple statuses across runs; ensure `canonical_id` collapses to one project and state transitions forward (verify `project_lifecycle`).
5. **Pagination off-by-one** — don't click next at `page_num >= max_pages`.
6. **TDD**: fixtures from `search_rows_20260614-123156.json` (real headers + the 8 invitation rows incl. the 5) + synthetic cases (column inserted/reordered, missing header → loud fail, each in-scope status, post-award excluded).
7. Apply in `apps/worker/.../browser_discovery.py`. Optionally patch `egp_crawler.py` for local A/B.

### WS2 — Make misses impossible to hide (P0 — elevated)
- **Anomaly flag**: `egp_found>0 && eligible==0` across pages → non-terminal anomaly, not silent `succeeded`. (Would have caught this bug immediately.)
- **Header-signature check**: record the detected header row; alert when it changes (early warning for the *next* column drift).
- **Telemetry enrichment (no migration)**: persist per-keyword `egp_found, rows_scanned, eligible, rejected_by_status, status_buckets, header_signature, skip_hits` into `crawl_tasks.result_json` (extends the shipped observability PR; stop overwriting page-scan events).
- **Structured outcome/reason codes (enum)** — shared with capture-attempts (B+ arch #3).
- **Aggregate alert** (Prometheus): eligibility-rate / header-drift / suspicious-scan.

### WS3 — Document-capture / backfill refinements (B+ review, P1)
- **P1a** — count only terminal statuses toward the cap; `ENQUEUED` = throttle; reconcile/expire stale `ENQUEUED`.
- **P1b / arch#2** — domain-aware retry: transient (`timeout/failed`) fast backoff; `no_documents` daily heartbeat to `proposal_submission_date`, else **30-day cap**.
- **P1c** — terminal UI state `ไม่พบเอกสารหลังตรวจซ้ำ` when attempts exhausted / deadline passed.
- **P2a** — fingerprint-only backfill fallback + visibility metric.
- **P2b** — fix/document profile-attribution heuristic.
- **arch#3** — structured reason codes on `document_capture_attempts` (shared enum w/ WS2).

### WS4 — Fleet observability & ops hardening (B+ review, P1)
- **arch#1** — fleet capture-rate alert; alert when backfill jobs enqueue but accrue no terminal rows.
- **P2c** — verify the backfill systemd timer actually runs (`compose run discovery-executor` vs keep-warm profile-gating); fix if it no-ops.
- **arch#4** — Track C SPOF hedge: queue-age alert.

### WS5 — Production repair (after WS1+WS2)
- Bounded re-scan of affected keywords/tenants through the fixed discovery → recovers the ~8/keyword missed invitation projects (incl. the 5) → triggers document capture.
- Acceptance: the 5 known project numbers exist in `projects`.

### WS6 — Strategic / defer (P2)
- Two-phase discovery (candidate collection → detail validation).
- Captured-HTML **replay harness** (seeded by the WS0 JSON — partially started).
- Parser card/`<div>` layout support (B+ P3).
- First-class crawl-observation records (migration) only if audit history needed.

## 5. Sequencing
WS0 ✅ → **WS1 ∥ WS2** (P0; share fixtures + reason-code enum) → **WS5** repair → **WS3 ∥ WS4** → WS6 defer.

## 6. Acceptance criteria
- `วิเคราะห์ข้อมูล` discovery yields the 8 invitation-stage projects (incl. the 5) — `eligible > 0`.
- Columns are header-derived; a missing/renamed required header fails **loud** (anomaly), not silent.
- `egp_found>0 && eligible==0` is flagged and alertable; header-signature drift alerts.
- The 5 known project numbers are in `projects` after WS5.
- Capture retries: transient = fast backoff; `no_documents` = daily heartbeat to deadline or 30-day cap; UI shows a terminal "gave up" state.

## 7. Risk register
- Fix is now **low-risk / high-confidence** — exact rows, exact column, and recovery of all 8 verified from live data.
- Residual: (a) full status-vocabulary coverage for the pre-award set (WS1 sub-task); (b) cross-announcement dedup/lifecycle under widening (verify in WS1); (c) the SKIP-keyword field behavior change (now checks real `ชื่อโครงการ`).

## 8. Changelog v1 → v2
- v1: hypothesized H1 (short-form status) / H2 (column drift) / "two bugs A+B" / status-filter staleness; plan gated on a diagnostic to decide between them.
- v2: diagnostic run → **single confirmed cause = column drift (off-by-one from inserted `หน่วยจัดซื้อ`)**; A/B proved faithful port; status compound match is correct; WS0 done; WS1 made concrete (header-derived mapping is the core); WS2 elevated (a `found>0&&eligible==0` canary would have caught it).

## 9. WS1 implementation summary (2026-06-14)

### What changed
- `packages/crawler-core/.../invitation_rules.py`: add `is_discoverable_stage_status` (invitation + pre-award include-markers); keep `is_invitation_stage_status`.
- `apps/worker/.../browser_discovery.py`: add `ResultsColumnsError`, `_extract_table_headers`, `resolve_results_columns` (header-derived column map; fail-loud on missing status/project_name/view). Rewire `_extract_search_row`, `_build_results_row_marker`, `_resolve_results_row_index`, `_build_candidate_row_snapshot`, the `_collect_keyword_projects` eligibility loop, and `navigate_to_project_by_row` to header-derived indices + `is_discoverable_stage_status`. Fix pagination off-by-one (no `next` click at `page_num >= max_pages`).
- `apps/worker/.../browser_close_check.py`: rewire `_find_matching_result_on_page` and `_collect_documents_for_observation` (view-click) to header-derived indices.
- `apps/worker/.../workflows/discover.py` + `packages/domain/.../project_ingest.py`: persistence gates use `is_discoverable_stage_status` (consistent with the row filter).
- Tests: 7-col fixtures; new `test_invitation_rules.py`; resolver + fail-loud + shifted-layout + pagination + close-check-view regression tests; gate-message + env-template-exclusion updates.

### TDD / verification evidence
- RED: 15 collect/navigate tests failed (`eligible_count=0`, status read from `cells[4]`=budget) after fixtures moved to the real 7-col layout.
- GREEN: `tests/phase1/test_worker_browser_discovery.py` + `test_invitation_rules.py` + `test_projects_and_runs_api.py` → 92 passed; ×3 consecutive (no flakiness). Regression sweep incl. `test_worker_live_discovery.py` → 143 passed. `tests/phase1 tests/phase2` → 516 passed.
- Lint: `ruff check apps/ packages/` → clean. Wiring: all new exports have non-test importers.
- QCHECK (manual Codex): 1 HIGH (close-check `cells[5]` view-click off-by-one) → FIXED + regression-tested; 0 CRITICAL. Report at `coding-logs/2026-06-13-09-53-19 …:396`.
- Known pre-existing, NOT WS1: `test_env_template` (2 config.py warmup vars missing from protected `.env` template) + `test_observability_stack` dashboard drift.

### Follow-ups (not in this PR)
- Precise status→ProjectState mapping for pre-award stages (currently method-inferred).
- WS2 (anomaly canary + telemetry), WS5 (prod re-scan repair), WS3/WS4 (capture/backfill refinements), per §4.
