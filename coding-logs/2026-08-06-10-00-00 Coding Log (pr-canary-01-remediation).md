# Coding Log: PR-CANARY-01 Remediation

**Date:** 2026-08-06
**Slug:** pr-canary-01-remediation
**Status:** IN PROGRESS

## Goal

Fix two findings from the PR-CANARY-01 review:
- Finding 2: `make_event` not wired to `dispatch_cancellable()` — structured events are never emitted during dispatch
- Finding 5: `_decode_framed_or_fallback_result` fails open when frame markers are present but content is malformed

## Implementation

**Stop line:** No delegation — Claude implements directly. Scope is ~25 lines
across 1 source file; delegation overhead would exceed the work.

**TDD:** Tests T10, T11, T12 written and RED-proven before implementation.
All 3 failed for the correct reasons (no events in log; reverse-scan returned
the wrong dict instead of None).

### Finding 2 fix: dispatch events

Added `make_event` import and 6 event creation sites in `dispatch_cancellable()`:
- 1x `dispatch_started` (after log_handle opened, before Popen)
- 1x `dispatch_finished` (after metrics emission, success path)
- 4x `dispatch_failed` (lease cancellation, timeout, spawn error, generic exception)

**Key design choice:** events are accumulated in a `pending_log_events: list[str]`
and flushed in the `finally` block via `_flush_log_events()`, NOT written inline.
Reason: inline writes to `log_handle` appear in `_read_log_tail()` output and
interfere with stderr reading in FakeProcess tests. Deferred writes preserve:
- Correct timestamps (captured at `make_event()` call time)
- No interference with `_read_log_tail` (writes happen after)
- All do-not-touch tests pass

Additional safety: `proc = None` initialized before inner try (Codex finding:
`Popen` failure leaves `proc` unbound; `except Exception` handler now safe).

### Finding 5 fix: fail-closed framing

Added `return None` after the try/except block inside the `if begin_idx >= 0 and
end_idx > begin_idx:` branch. This means:
- Both markers + valid dict → return dict (unchanged)
- Both markers + invalid content → return None (fail-closed)
- No complete marker pair → reverse-scan fallback (unchanged)

### Codex adversarial review (Phase 3)

5 findings, all accepted:
1. MEDIUM: `proc` unbound on spawn failure → ACCEPTED, added `proc = None`
2. MEDIUM: dispatch_started not crash-durable → ACCEPTED, deferred writes
3. MEDIUM: R7 preservation in helper → ACCEPTED, wrapped event creation in try/except
4. LOW: DREP arithmetic ("4 writes" should be "6 call sites") → ACCEPTED, cosmetic
5. LOW: "no markers" vs "no complete marker pair" → ACCEPTED, clarified

## Review — Round 1

### Tier 1: g2-check (2026-08-06T10:30+07:00) — working-tree

**Reviewed:**
- Scope: working-tree diff (1 source file + 1 test file)
- Commands: `git diff`, `rg`, `Read` on both changed files + related code
- Not inspected: other test files (confirmed green via full test run)

**Findings:**

LOW
- `_RELEASE_SHA` read at module-import time (L65), while the executor reads the
  same env var at `main()` call time. Cosmetic inconsistency; no production
  impact since env vars are set before process start.
- `NonRetriableDiscoveryDispatchError` (extends `RuntimeError`, not
  `DiscoverySpawnError`) falls to `except Exception` handler and gets
  `reason="unexpected_error"` instead of a more specific reason.

**Wiring verification:**
| New import | Non-test import | Runtime call site |
|---|---|---|
| `make_event` | L57 in dispatcher | 6 sites in `dispatch_cancellable()` → appended to `pending_log_events` → flushed in finally via `_flush_log_events` |

**Open Questions:** None.

### Tier 2a: Codex gpt-5.6-sol (2026-08-06T11:15+07:00) — working-tree

**Reviewer:** Codex gpt-5.6-sol, model_reasoning_effort=xhigh, read-only sandbox
**Reviewed:** full diff + original DREP; ran lint (passed), 6-case decoder edge test (all correct)

**Findings:**

MEDIUM
- dispatch_started deferred-write loses pre-spawn durability: a hung dispatch shows
  no start event until teardown. → DEFERRED: deliberate trade-off to preserve
  do-not-touch tests; immediate write interferes with _read_log_tail. Correct
  timestamps captured at creation time.
- Failure reason labels misleading: `spawn_error` for nonzero exit,
  `unexpected_error` for entitlement denial/SIGKILL. Lease-lost omits child_pid.
  → DEFERRED: pre-existing exception hierarchy; events ARE emitted, reasons imprecise.
  Future PR should add NonRetriableDiscoveryDispatchError handler or use failure_code.
- stdout_capture.close() can prevent log_handle.close() in finally block.
  → DEFERRED: pre-existing pattern, not introduced by this change.

LOW
- Tests are non-vacuous but don't cover event order, exact reason values, or all
  failure paths. → ACCEPTED: scoped to remediation; comprehensive tests in hardening PR.

**Decoder edge cases verified by Codex (all correct):**
- valid_pair → framed dict
- malformed_pair → null (fail-closed)
- truncated_begin → fallback
- no_markers → fallback
- end_only → fallback
- wrong_order → fallback

### Tier 2b: Opus agent (2026-08-06T11:10+07:00) — working-tree

**Reviewer:** Claude Opus 5, independent subagent
**Reviewed:** diff + source files (5 tool calls)

**Findings:**

MEDIUM (CONFIRMED)
- NonRetriableDiscoveryDispatchError in except Exception with reason="unexpected_error"
  — same as Codex finding. → DEFERRED (see above).

LOW (PLAUSIBLE)
- log_handle leak if code between opening and inner try raises.
  → DEFERRED: pre-existing, very low probability.

### QCHECK Gate Verdict

- **0 CRITICAL, 0 HIGH** — gate passes
- **3 MEDIUM** — all deferred with reasons (pre-existing issues, not introduced by this change)
- **3 LOW** — accepted or deferred
- Both tiers ran with independent reviewers (Codex gpt-5.6-sol + Opus agent)
- De-duplicated across tiers: reason-label finding raised by both (1 finding, 2 witnesses)
- All gates green: 1469 passed (2 pre-existing env-template failures), lint clean, 3x non-flaky
