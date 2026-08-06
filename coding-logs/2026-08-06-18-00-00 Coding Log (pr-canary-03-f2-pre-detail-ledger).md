# Coding Log: PR-CANARY-03 F2 — Pre-Detail Candidate Ledger Write

**Date:** 2026-08-06
**Slug:** pr-canary-03-f2-pre-detail-ledger
**Branch:** feat/canary-03-f2-pre-detail-ledger
**Worktree:** /Users/subhajlimanond/dev/egp-canary-03-f2
**Status:** IN PROGRESS (planning complete → implementation)

## Planning (g2-planning) — COMPLETE

DREP: `coding-logs/2026-08-06-18-00-00 DREP (pr-canary-03-f2-pre-detail-ledger).md`.

Phase 1 exploration confirmed the gap: the durable `record_accepted` fires only via the
post-detail `project_callback(payload)` (`browser_discovery.py:582-583`), so a timeout /
browser-death / `payload is None` between `scan.record_accepted()` (`:504`, in-memory) and the
callback leaves no durable row. Both worker entrypoints (`main.py:152`, `agent_runtime.py:221`)
reach the browser via `run_discover_workflow` → `crawl_live_discovery`, so the fix in the workflow
+ browser functions covers both.

**Phase 3 (Codex gpt-5.6-sol xhigh) returned BLOCK on draft 1** — 13 findings, all dispositioned in
DREP §11. Material fixes folded in:
- **C-2 (critical):** every test was vacuous to an un-forwarded callback → added **T6** proving the
  real `crawl_live_discovery` forwards `candidate_callback` to `_collect_keyword_projects`.
- **C-3:** T2 RED-proof was factually wrong (`_raise_browser_closed` converts only "has been closed"
  messages) → rewrote T2 with a pathological message + `not isinstance(BrowserClosedDuringKeyword)`
  + empty open-spy to truly distinguish inside-vs-outside `try`.
- **C-6 (critical):** threaded `candidate_key` leaked into `raw_snapshot`/task payload (product state,
  violating `apps/worker/AGENTS.md:28`) → `_persist_discovered_project` now **pops** the key before
  building the product event (R6).
- **C-4/C-5/C-9/C-11:** hardened T5 (divergent search/detail names, `live_include_documents=False`,
  leak assertions), authoritative `payload["candidate_key"] =` (not `setdefault`), T1 shared-order log.
- **C-13:** conditional callback forwarding so the existing resume fake stays green.

Design: single slice **S1**, owner **Claude** (Q0 — correctness-critical ledger/crawler path,
fail-closed control flow that must not be mis-wrapped). Position-based key + resume page/ordinal
accuracy explicitly deferred to the candidate-identity slice (§1 Non-Goals, §9-D).

## Implementation (g2-coding) — Claude, no delegation

**Stop line:** none. Q0 fired (correctness-critical ledger/crawler write + fail-closed control flow) →
Claude implemented the whole slice. Per Phase 2c-ter the TDD standard still held: all 6 acceptance
tests were authored and **RED-proven for the predicted reasons** before any product code:
- T1/T2/T3/T6 → `TypeError: ... got an unexpected keyword argument 'candidate_callback'` (clean RED).
- T4/T5 → `assert callable(None)` ("workflow must pass candidate_callback") (clean RED).

Then implemented C1–C4 → all 6 GREEN. No mutation testing needed: every test had a genuine RED.

**Anchor refinement found during TDD (C4):** `safe_discovered = _task_safe_payload(discovered)` runs at
`discover.py:539`, BEFORE the candidate block (~551). So the R6 `candidate_key` pop had to move to the
TOP of `_persist_discovered_project` (right after the `nonlocal` block), not inside the candidate block
as the draft FN4 said. T5's leak assertions (`"candidate_key" not in task payload / raw_snapshot`)
verify the pop is early enough. Logged here per the "honest anchor" rule.

**Files changed (product):**
- `browser_discovery.py`: `crawl_live_discovery` + `_collect_keyword_projects` gain optional
  `candidate_callback`; eligible rows tagged with `page_number`/`eligible_ordinal`; callback invoked
  **outside** the per-row `try`; `candidate_key` threaded authoritatively onto the payload; forwarding
  is **conditional** (only when non-None) so the existing resume fake is untouched.
- `workflows/discover.py`: new inner `_record_live_candidate` (compute key + `record_accepted`, no
  per-keyword re-auth); passed as `candidate_callback`; `_persist_discovered_project` pops
  `candidate_key` at the top and only records acceptance on the direct path.

**Gates (Claude ran each):**
- 6 new tests GREEN; full four target suites **164 passed** (158 baseline + 6).
- Broader discovery/dispatcher/worker regression sweep (8 files) **119 passed**.
- ruff clean on all 4 changed files; `compileall apps/worker/src` OK.
- 3× flakiness on the 6 new tests: stable.
- Diff audit: only the 4 intended files changed (+2 coding-log docs); Do-Not-Touch list fully
  respected (repo/key/migrations/main.py/agent_runtime.py/dispatcher/resume-test all untouched); no
  fabricated/mocked/randomized data.

## QCHECK (g2-qcheck) — author Claude, reviewers independent

### Round 1 (framing: contract-correctness)
- **Tier 1 — independent Opus agent (`/code-review`-equivalent):** No CRITICAL/HIGH. Verified R1–R7
  at real call sites, ran all 6 tests + full affected suites (155 pass), confirmed each test
  non-vacuous by revert mutation. Two LOW: (L1) `accepted` can exceed `persisted+failed` on benign
  dedupe/late-stage-ignore (pre-detail accounting is truthful; F4 owns the run-summary invariant);
  (L2) resume ordinal divergence (informational).
- **Tier 2 — Codex gpt-5.6-sol (xhigh):** R1,R2,R3,R5,R6,R7 **Pass**. Two findings on R4:
  - **HIGH — resume re-keying duplicate.** On a Playwright `"has been closed"` error DURING detail
    extraction, the generic row handler (`browser_discovery.py:701-703`) raises
    `BrowserClosedDuringKeyword` WITHOUT `_mark_row_seen` (unlike the sibling handlers at :690-700).
    On resume the row is re-scanned with the logical page reset to 1 → a different position key → a
    second `accepted` row; the original is orphaned. **Disposition: DEFERRED** to the
    candidate-identity slice + F4 (run authority) + F5 (reconciliation), with reason:
    (1) it is the documented Non-Goal §1/§9-D (position-based key instability on resume);
    (2) no correct in-scope fix exists — a complete fix needs a content-based key (row_marker/
    project_number), and F2's do-not-touch list forbids changing `compute_candidate_key`;
    (3) it is SAFE — over-count only, the project IS still persisted on the resume pass (verified:
    no data loss), and the orphan `accepted` row is exactly what F4/F5 are chartered to close;
    (4) the naive in-scope "fix" (mark the row seen on :701) would SKIP the row on resume → the
    project would never be persisted → real data loss, strictly worse. Downgraded to MEDIUM for F2
    scope. Owners: candidate-identity slice (key), F4 (run-authority), F5 (reconciliation).
  - **MEDIUM — direct-path key spoofing.** `_persist_discovered_project` trusted any `candidate_key`
    FIELD in the payload as proof of prior acceptance (skipping `record_accepted`), so a direct
    (`discovered_projects`) payload could spoof acceptance → `finalize` silently no-ops → no accounting.
    **Disposition: FIXED.** The authoritative key now arrives ONLY via a `candidate_key` PARAMETER
    (provenance) set by the live path's `_persist_live_project`; the payload field is popped and
    ignored (sanitized for both leak-prevention and anti-spoof). Regression test **T7**
    (`test_direct_path_ignores_untrusted_candidate_key_field`) RED-proven (pre-fix total==0) → GREEN.
  - **Test-vacuity note:** Codex flagged T4/T5 as vacuous to the *real browser ordering* because they
    use a fake `crawl_live_discovery`. **Acknowledged, no action:** T4/T5 are WORKFLOW-integration
    tests (durable-write + wiring + no-leak + finalize); the real browser ordering is covered by **T1**
    (real `_collect_keyword_projects`, ordered `seq`) ∘ **T6** (real `crawl_live_discovery` forwarding).
    No single test runs the full real stack because CI has no browser — this is the intended split, and
    Codex itself confirmed T1/T2/T3/T6 are non-vacuous.

Round-1 remediation: MEDIUM fixed (+T7); gates re-run GREEN (257 passed across target + discovery-
adjacent suites; ruff clean; compileall OK; 3× stable).

### Round 2 (framing: adversarial provenance/security, on the REMEDIATED tree)
Both tiers re-reviewed after the Round-1 provenance fix.
- **Tier 1 — independent Opus agent:** Provenance fix **sound** (spoof + leak closed, R6 airtight after the
  signature change; empirically verified). D1/D2/D3 all analysed; resume deferral **safe** (project
  retained). **No CRITICAL/HIGH.** One **new MEDIUM**: F2's pre-detail `record_accepted` also orphans an
  `accepted` row on **post-detail dedup** — when ≥2 eligible rows resolve to the same detail
  `project_number` (the same project under multiple keywords = PRD acceptance test 1), the duplicates are
  deduped at `browser_discovery.py:610` and their pre-detail candidates are never finalized, inflating
  `accepted` on *successful* runs. **Disposition: DEFERRED to F4/F5** (Tier 1's own recommendation):
  the repo already has `finalize_dropped` (`candidate_attempt_repo.py:326`, currently unwired) — F4
  ("make finalization authoritative") wires a "dropped" seam at the dedup point. **Verified LATENT:**
  `rg` confirms `get_run_candidate_summary` has **no production consumer** and `finalize_dropped` has
  **no production caller** — nothing depends on the count today. Over-count only; product/project state
  correct. Owner: F4 (finalization authority) + F5 (reconciliation).
- **Tier 2 — Codex gpt-5.6-sol (xhigh):** Provenance fix **closed** for all in-repo callers; the fix did
  not move the leak/spoof; `str(threaded_key)` harmless; no signature-change regression. Correctly
  **refuted D2** (my "impossible without content-based key" claim): a same-process memo of the returned
  key by dedupe identity WOULD close the common reconnect case without touching `compute_candidate_key`.
  **Disposition:** DREP §1/§9-D **corrected** to state the memo is *deferred, not impossible* (it threads
  delicate resume/seen/dedupe state with its own regression risk; the residual is safe; the complete
  reordered/cross-process fix still needs a content-based key = candidate-identity slice). One **LOW**:
  a caller-supplied nested `raw_snapshot={"candidate_key":…}` isn't recursively sanitized — cannot spoof
  or leak our authoritative key (only the top-level transport field matters); **no action**. Codex's
  "HIGH — change not committed" is **not a code defect**: it diffed `origin/main...HEAD` (empty pre-commit);
  it explicitly confirmed "after committing the exact reviewed worktree, no additional above-LOW defect in
  the provenance remediation itself."

**Round-2 disposition summary:** zero open CRITICAL/HIGH; both tiers agree the tree is safe to ship for
product correctness. All MEDIUMs fixed-or-deferred-with-owner; the two deferred items (resume re-key,
post-detail-dedup) are the SAME safe over-count class (accepted may exceed persisted+failed on a healthy
run), **latent** (no ledger consumer yet), and chartered to F4 (run authority + `finalize_dropped`) + F5
(reconciliation) + the candidate-identity slice (content-based key). No further code change in Round 2
(doc-only), so gates remain green. **Gate: PASS.**

**Deferred to downstream PR-CANARY-03 slices (explicit follow-ups):**
1. **F4** — wire `finalize_dropped` at the post-detail dedup seam (`browser_discovery.py:610`) so deduped
   candidates terminalize as `dropped`; make run success forbid open `accepted` rows.
2. **F5** — reconcile leftover `accepted` rows (incl. resume orphans) to `unknown`/`worker_lost` on all
   abnormal terminal paths + the agent runtime.
3. **candidate-identity slice** — content-based `candidate_key` (row_marker/project_number) to eliminate
   resume re-keying; or a same-process key memo as an interim.

## Goal

Fix the F2 HIGH finding from the consolidated PR-CANARY-01..03 review
(`egp-ops-main/coding-logs/2026-08-05-17-58-04 …canary-hardening.md`, Findings
2026-08-06 07:48:44):

> **[PR-CANARY-03] Live candidates are recorded after detail navigation, so the
> ledger omits the exact failures it was designed to expose.**

Move the durable `record_accepted` ledger write to BEFORE detail navigation in the
live browser discovery flow, so a timeout / browser-death / invalid-detail /
`payload is None` / recovery failure after accepted-row selection still leaves a
queryable `accepted` candidate row. Fail closed: if the durable acceptance write
fails, stop the crawl.

See the DREP: `coding-logs/2026-08-06-18-00-00 DREP (pr-canary-03-f2-pre-detail-ledger).md`.
