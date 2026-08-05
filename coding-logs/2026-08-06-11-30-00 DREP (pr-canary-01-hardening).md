# DREP: PR-CANARY-01 Hardening — exception handlers + resource cleanup

## §0 Repo Profile

Same as PR-CANARY-01 remediation DREP §0. No new deps, no migration, no UI.

- **Test:** `./.venv/bin/python -m pytest tests/phase1/test_structured_logging.py tests/phase1/test_api_discovery_spawn.py tests/phase2/test_immediate_discover.py tests/phase2/test_discovery_dispatch.py tests/phase3/test_discovery_cancellation_poll.py tests/phase3/test_crawler_agent_runtime.py -v`
- **Lint:** `ruff check apps/ packages/ tests/ scripts/`
- **Build:** `python -m compileall apps packages`
- **Coding log:** `coding-logs/2026-08-06-11-30-00 Coding Log (pr-canary-01-hardening).md`
- **MUST NOT:** type hints on all signatures; no secrets committed; no `any` in TS

## §1 Goal / Non-Goals

**Goal:** Fix 3 pre-existing MEDIUM findings surfaced by the PR-CANARY-01
remediation review: (1) add a `NonRetriableDiscoveryDispatchError` exception
handler with a specific reason label, (2) wrap `stdout_capture.close()` and
`log_handle.close()` in independent try/except guards, (3) ensure `log_handle`
is closed even if code between its opening and the inner try raises.

**Non-Goals:**
- No change to event creation logic or event vocabulary
- No change to `_decode_framed_or_fallback_result` (already fixed in #200)
- No change to the observability package
- No new dependencies, routes, or migrations
- No change to `_RELEASE_SHA` import-time read (cosmetic inconsistency, not a bug)

## §2 Requirements

| ID | Requirement |
|----|-------------|
| R1 | `NonRetriableDiscoveryDispatchError` is caught by a dedicated handler before `except Exception`, emitting a `dispatch_failed` event with `reason="non_retriable_error"` and `child_pid`. |
| R2 | `stdout_capture.close()` failure does not prevent `log_handle.close()` from running. Both closes are independently guarded. |
| R3 | `log_handle` is closed if any exception occurs between its opening (L897) and the inner try (L950), including `json.dumps` or `SpooledTemporaryFile` failures. |

## §3 Change Contract

| ID | Path | Action | Anchor | New exports | Purpose |
|----|------|--------|--------|-------------|---------|
| F1 | `apps/api/src/egp_api/services/discovery_worker_dispatcher.py` | MODIFY | `dispatch_cancellable()` exception handlers L1118-1149; finally block L1150-1168; log_handle scope L893-950 | — | Add NonRetriable handler, guard closes, widen log_handle cleanup scope |

## §4 Function Contracts

```
FN1  (modification) dispatch_cancellable() — exception handler ordering
     File:        F1
     Changes:     Insert `except NonRetriableDiscoveryDispatchError:` between
                  `except DiscoverySpawnError:` and `except Exception:`.
                  Event: dispatch_failed with reason="non_retriable_error",
                  child_pid=getattr(proc, "pid", None).
     Post:        entitlement denial and signal termination get specific
                  reason labels; generic Exception only catches truly unexpected.

FN2  (modification) dispatch_cancellable() — finally block cleanup
     File:        F1
     Changes:     Wrap stdout_capture.close() and log_handle.close() in
                  independent try/except guards. Move log_handle.close() to
                  an outer try/finally that covers the gap between log_handle
                  opening and the inner try.
     Post:        stdout_capture failure never prevents log_handle cleanup;
                  log_handle never leaks regardless of where an exception occurs.
```

## §5 Test Plan

```
T1   test_non_retriable_error_gets_specific_dispatch_failed_reason
     File:      tests/phase1/test_structured_logging.py
     Covers:    R1
     Type:      unit (monkeypatch + FakeProcess)
     Arrange:   FakeProcess returns stderr with entitlement_denied JSON;
                returncode=1. Use tmp_path for artifact_root.
     Act:       call spawner() and catch NonRetriableDiscoveryDispatchError
     Assert:    worker.log contains dispatch_failed event with
                reason="non_retriable_error" and child_pid present
     RED-proof: before the handler exists, NonRetriableDiscoveryDispatchError
                falls to except Exception → reason="unexpected_error"
     Fixtures:  monkeypatch, tmp_path

T2   test_stdout_capture_close_failure_does_not_prevent_log_handle_close
     File:      tests/phase1/test_structured_logging.py
     Covers:    R2
     Type:      unit (monkeypatch + FakeProcess + patched SpooledTemporaryFile)
     Arrange:   FakeProcess succeeds; monkeypatch SpooledTemporaryFile.close
                to raise OSError. Use tmp_path for artifact_root.
     Act:       call spawner() (should succeed despite close failure)
     Assert:    worker.log file handle is closed (file is readable and
                contains dispatch events); no OSError propagated
     RED-proof: before the guard, SpooledTemporaryFile.close() raises →
                log_handle.close() never runs → the test that checks for
                successful completion would fail with the unguarded OSError
     Fixtures:  monkeypatch, tmp_path

T3   test_log_handle_closed_on_payload_serialization_failure
     File:      tests/phase1/test_structured_logging.py
     Covers:    R3
     Type:      unit (monkeypatch)
     Arrange:   monkeypatch json.dumps to raise TypeError on the first call
                after log_handle is opened (the payload serialization).
                Use tmp_path for artifact_root.
     Act:       call spawner() and catch the exception
     Assert:    worker.log file handle is closed (not leaked)
     RED-proof: before the outer try/finally, TypeError from json.dumps
                bypasses the inner finally → log_handle leaks (file handle
                not closed). After the fix, the outer finally catches it.
     Fixtures:  monkeypatch, tmp_path
```

## §6 Traceability Matrix

| Req | Fulfilled at — call site | Tests | Files | Slice |
|-----|--------------------------|-------|-------|-------|
| R1 | `dispatch_cancellable()` → new `except NonRetriableDiscoveryDispatchError:` handler with `make_event("dispatch_failed", reason="non_retriable_error", child_pid=...)` | T1 | F1 | S1 |
| R2 | `dispatch_cancellable()` finally block → `try: stdout_capture.close() except Exception: pass` + separate `try: log_handle.close() except Exception: pass` | T2 | F1 | S1 |
| R3 | `dispatch_cancellable()` → outer `try...finally` wrapping the gap between log_handle opening and inner try, with `log_handle.close()` in the outer finally | T3 | F1 | S1 |

## §7 Wiring Verification

No new components. All changes modify existing wired code.

## §8 Slice Plan

| ID | Scope | Owner | Stop line | Oracle | Done when |
|----|-------|-------|-----------|--------|-----------|
| S1 | F1, T1-T3 | **Claude** | — (Q0: exception handler ordering + resource cleanup = correctness boundary) | T1-T3 green + all do-not-touch tests green + lint | All tests green, lint clean |

## §9 Risks

| Risk | Trigger | Gate | Rollback |
|------|---------|------|----------|
| Outer try/finally changes nesting depth | Indentation error | lint + existing tests | Revert |
| NonRetriable handler order wrong | New handler catches wrong exceptions | T1 asserts specific reason | Revert handler |

## §10 Do-Not-Touch List

Same as PR-CANARY-01 remediation DREP §10. All existing tests in phase1/phase2/phase3
must stay green and must not be modified. The observability package, worker main.py,
and discovery_dispatch.py executor must not change.
