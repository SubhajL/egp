# Coding Log: PR-CANARY-01 Hardening

**Date:** 2026-08-06
**Slug:** pr-canary-01-hardening
**Status:** IN PROGRESS

## Goal

Fix 3 MEDIUM deferred findings from the PR-CANARY-01 remediation review (#200):
1. NonRetriableDiscoveryDispatchError lands in generic `except Exception` with `reason="unexpected_error"` instead of a specific reason
2. `stdout_capture.close()` can prevent `log_handle.close()` from running in the finally block
3. `log_handle` leak if code between opening and inner try raises

## Implementation

**Stop line:** Claude implements directly. Q0: exception handler ordering is a
correctness boundary. Scope is ~40 lines in 1 file. No delegation.

**TDD:** Tests T13, T14, T15 written and RED-proven before implementation.
- T13: `reason="unexpected_error"` (wrong) vs `"non_retriable_error"` (expected)
- T14: `OSError` from `stdout_capture.close()` propagated (unguarded)
- T15: `close_tracker` empty — `log_handle.close()` never called after json.dumps failure

### Fix 1: NonRetriableDiscoveryDispatchError handler

Added `except NonRetriableDiscoveryDispatchError:` handler between `except
DiscoverySpawnError:` and `except Exception:`. Since `NonRetriableDiscoveryDispatchError`
extends `RuntimeError` (not `DiscoverySpawnError`), these are sibling hierarchies —
ordering between them is for readability, not catch semantics. The handler emits
`dispatch_failed` with `reason="non_retriable_error"` and `child_pid`.

### Fix 2: Independent close guards

Wrapped both `stdout_capture.close()` and `log_handle.close()` in independent
try/except guards in the inner finally block. A failure in one no longer prevents
the other from running.

### Fix 3: log_handle leak on gap failure

Wrapped the gap between log_handle opening (L897) and the inner try (L955) —
which contains `json.dumps()` and `SpooledTemporaryFile()` — in a try/except
that flushes pending events and closes log_handle before re-raising. No
double-close possible: this handler and the inner finally are mutually exclusive
paths (if the gap handler fires, the inner try is never entered).

## Review — Round 1

### Tier 1: Opus agent (2026-08-06T12:00+07:00) — working-tree

**Reviewer:** Claude Opus 5, independent subagent (20 tool calls)
**Scope:** `git diff origin/main -- apps/ tests/` in worktree

**Findings:** 0

- Exception handler ordering confirmed correct (sibling RuntimeError subclasses)
- No double-close possible (gap handler and finally are mutually exclusive paths)
- Payload-failure cleanup correctly flushes + closes log_handle before re-raising
- All 3 tests verified as non-vacuous
- Restored the accidentally-removed "Last-resort reap" production-incident comment

### Tier 2: Codex gpt-5.6-sol (2026-08-06T11:45+07:00) — working-tree

**Reviewer:** Codex gpt-5.6-sol, model_reasoning_effort=high, read-only sandbox

**Findings:**

MEDIUM
- T14 does not verify its stated contract — checks `dispatch_finished` event
  (flushed before the injected close failure) but doesn't assert `log_handle.close()`
  ran. → FIXED: added close spy via `Path.open` monkeypatch that tracks close calls.

**Verification:** Exception ordering correct, cleanup re-raises correctly, no
double-close, None guard is safe, T13/T15 non-vacuous. T14 partially so → fixed.

### QCHECK Gate Verdict

- **0 CRITICAL, 0 HIGH** — gate passes
- **1 MEDIUM** (Codex) → FIXED (T14 close spy added)
- Both tiers ran with independent reviewers
- Re-run after fix: 86 passed, lint clean, 3x non-flaky
- Codex finding fixed → both tiers re-validated by gate re-run
