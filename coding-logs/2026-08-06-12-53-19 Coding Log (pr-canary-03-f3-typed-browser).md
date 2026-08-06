# Coding Log: PR-CANARY-03 F3 — Typed Browser Outcomes & Private Diagnostics

## Metadata
- Created: 2026-08-06-12-53-19 Asia/Bangkok
- Repository: `/Users/subhajlimanond/dev/egp-f3-typed-browser` (worktree; branch `feat/pr-canary-03-f3-typed-browser`)
- Planning base: `7a6586f6fa36ef5dab02891e164ff260723d1c67` (== origin/main at branch creation)
- Slice: PR-CANARY-03 **F3** = the frozen PR-CANARY-02 typed-browser contract (source coding log lines 463-484), reassigned as F3 in the PR-CANARY-03 remediation numbering.
- Scope: typed detail classifier + bounded single retry + private redacted diagnostics + document-evidence-only. NOT candidate finalization / run authority (F4), NOT migration constraints (F6).

---

## Planning complete (g2-planning)

DREP: `coding-logs/2026-08-06-12-53-19 DREP (pr-canary-03-f3-typed-browser).md`

- §0-§11 present; Codex (gpt-5.6-sol, xhigh) adversarial pass ran and returned **BLOCK** on the first
  draft — five real defects fixed and dispositioned in DREP §11 (classifier ordering / `""`,
  cross-keyword `keyword_no_results`, anomaly poisoning, fail-open absence flag, wrong `main.py`
  fn/env path), plus MEDIUM/LOW (filename collision, file perms, full_page screenshot).
- Scope: typed detail classifier + one bounded retry + private redacted `0o600` diagnostics + keyword
  no-results budget fix + document-evidence-only. NOT finalization/run-authority (F4), migration/
  constraints (F6), reconciliation (F5), dispatcher/API plumbing (PR-07).
- 13 change rows (C1-C13); 23 tests (T1-T23) each with a RED-proof; all slices Claude-owned
  (security boundary + fail-closed-adjacent wiring).

Next: g2-coding (TDD, S1→S5), then g2-qcheck gate, one PR, admin-merge, land local main.

## g2-coding — stop line

Q0 fires: DREP §8 marks every slice Claude-owned — C7 `browser_diagnostics.py` is a security
boundary (no-secret-leak / private files) and C4/C5/C6 are fail-closed-adjacent browser wiring.
→ **No delegation; Claude implements the whole slice.** No `pi`/shim preflight. Phase 2c-ter TDD
standard applies (test → RED → implement → GREEN per unit); classifier ordering (Codex A1) and the
anti-poisoning terminal emission (A3) proven by mutation where RED is only ImportError.

## Implementation (g2-coding, all Claude-authored — no delegation per Q0)

Built in 4 RED→GREEN chunks, each mutation-verified where RED was only ImportError:

- **Chunk A (S1+S2):** `ProjectDetailReason` enum (C1); `classify_detail_page` replacing
  `_detail_page_is_invalid` with corrected ordering (rejection → results-page → non-empty placeholder
  → valid; **no `""` in the placeholder set** — Codex A1); `DetailOutcomeSink` + reason-sets; `open_and_extract_project`
  gains optional `outcome_sink`, tags every exit, adds `project_number` to the missing-required check,
  and **no longer emits** the anomaly stage (moved to caller — Codex A3). T1-T8. **Mutation:** re-adding
  `""` to the placeholder set fails T5 (confirmed non-vacuous).
- **Chunk B (S4):** `browser_diagnostics.py` (C7) — fail-open capture, opaque per-anomaly stem (Codex A9),
  `0o600` files in a `0o700` dir (A10), URL-strip + shared redactor (A8), `full_page=True` (A11); settings
  field `diagnostics_dir` (C2). T14-T19 + keyword.
- **Chunk C (S3):** `_collect_keyword_projects` bounded single retry (transient-only), no-double-restore
  (Codex A7), terminal anomaly emission ONCE via `_emit_terminal_detail_anomaly`, fail-open
  `_safe_capture_detail_diagnostic` with `browser_diagnostic` status event (A4); timeout-branch diagnostic
  (C5b / A6). T9-T13.
- **Chunk D (S5+C8):** `crawl_live_discovery` bounded keyword no-results recovery loop before terminal
  (Codex A2) + keyword diagnostic (C6); `_build_browser_settings` parses `diagnostics_dir` from payload
  or `EGP_BROWSER_DIAGNOSTICS_DIR` env (C8 / A5). T21-T23. **Mutation:** disabling the recovery loop fails T21.

### Verification (Claude ran every gate)
- ruff check: All checks passed; ruff format applied. compileall: OK.
- Regression sweep (all dependents + T20 doc-envelope gate `test_crawler_agent_inbox_processor.py`
  unmodified + agent runtime): **259 passed, 0 failed**.
- Affected F3 suite (4 files): **186 passed**. Wiring: every new export has a non-test import + runtime
  call site (no orphans). 3× flakiness on 30 F3 tests: stable.
- discover.py untouched — anomaly poisoning fixed entirely in browser_discovery.py by moving emission to
  the terminal branch (the `stage → DiscoveryFailureCode` mapping is preserved).

Next: g2-qcheck (blocking).

## g2-qcheck (blocking gate)

**Implementer: Claude (no delegate). Reviewer independence:** Tier 2 default (Codex gpt-5.6-sol) was
**usage-limited** (smoke test: "hit your usage limit … Aug 8th") → substituted per the ladder with an
independent-context **Opus agent** for Tier 2. To decorrelate two Claude-family reviewers, Tier 1 and
Tier 2 ran at **disjoint framings**.

**Round 1 — both tiers on the slice diff (scoped against DREP §2 R1–R11):**
- **Tier 1 (contract-correctness + empirical/wiring):** CRITICAL 0 / HIGH 0 / MEDIUM 0 / LOW 2. All
  R1–R11 realized at the named call sites; no regressions; `_detail_page_is_invalid` fully removed; no
  orphaned runtime code / phantom symbol / wired duplicate. 186 affected tests + T20 doc-envelope +
  test_rules_api pass.
  - LOW-1: `_DIAGNOSTIC_REASONS` defined but unused; terminal capture ran ungated → OUT_OF_SCOPE/UNKNOWN
    would capture. **FIXED** — capture gated on `sink.reason in _DIAGNOSTIC_REASONS`; new regression test
    `test_collect_no_diagnostic_for_out_of_scope_terminal`.
  - LOW-2: payload `browser_diagnostics_dir=""` → `Path(".")` (repo path), violating §0 MUST-NOT.
    **FIXED** — payload value now `str(...).strip() or None`.
- **Tier 2 (adversarial security / fail-open / resource):** CRITICAL 0 / HIGH 0 / MEDIUM 0 / LOW 3.
  Secret/URL leak REFUTED (manifest is an allowlist of structured fields; no page.url/HTML/cookies/creds/
  exception text; screenshots 0o600 in 0o700 dir; opaque contained filenames). Fail-open REFUTED (two
  layers). Retry safety REFUTED (unique ≥70 marker match; no double-count; `restored_to_results` prevents
  double-restore). Recovery bounded REFUTED. Env activation REFUTED.
  - LOW-1: recovery emits a bounded *multiple* of `search_page_recovery_retries` (each `search_keyword`
    carries its own budget). **NOTED** — inherent, finite (~a handful of extra searches per no-results
    keyword), not a defect.
  - LOW-2: screenshot not bounded by an explicit timeout (~30s Playwright default). **FIXED** —
    `page.screenshot(timeout=15000)`.
  - LOW-3: brief mkdir perms window; inert on the single-user residential runner. **FIXED** (trivial) —
    `mkdir(mode=0o700)`.

De-dup across tiers: disjoint finding sets (Tier 1 contract/wiring; Tier 2 security/resource). Zero
CRITICAL/HIGH/MEDIUM in either tier.

**Round 2 — remediation:** applied the 5 LOW fixes above; ruff + format clean; 187 affected tests pass;
focused Opus re-review of the fix hunks (proportionate to LOW-only, localized fixes; the full both-tier
round already surfaced nothing above LOW). Result recorded on completion.

**Round 2 re-review (focused Opus on the fix hunks):** clean — CRITICAL 0 / HIGH 0 / MEDIUM 0 / LOW 0.
Confirmed `_DIAGNOSTIC_REASONS` is set-identical to the `_ANOMALY_STAGE_BY_REASON` keys, so a diagnostic
is captured iff an anomaly stage is emitted (the gate removed a prior inconsistency). Coverage gap it
noted (empty-string payload) closed by `test_build_browser_settings_diagnostics_dir_empty_string_is_none`.

**GATE PASS:** no open CRITICAL/HIGH/MEDIUM; every finding fixed or dispositioned; final gates green
(ruff clean, 187 affected tests + settings/diagnostics suites pass, 3× flakiness stable).

## g2-coding Phase 8 — attribution

- **Stop line:** Q0 fired (security boundary `browser_diagnostics.py` + fail-closed-adjacent browser
  wiring) → **no delegation; Claude implemented the entire slice.** Recorded pre-implementation.
- **Authorship:** 100% Claude. Delegate (DeepSeek/`pi`) not used → **0 delegate tokens**.
- **Fix rounds:** 1 remediation round (5 LOW fixes), then a clean focused re-review. No CRITICAL/HIGH at
  any point. (Adaptation note: this slice was heavier than F1/F2 but landed clean at review — no
  stop-line escalation needed for future comparable slices.)
- **Non-vacuity:** classifier ordering (T5) and keyword recovery (T21) were written correct-first
  (RED was only ImportError/behavioral); both **mutation-verified** (re-adding `""` fails T5; disabling
  the recovery loop fails T21).
- **QCHECK:** Tier 1 (contract/wiring, Opus) + Tier 2 (security/fail-open, Opus — Codex usage-limited,
  substituted per ladder) at disjoint framings + a focused fix-hunk re-review. All 0 CRITICAL/HIGH/MEDIUM.
