# DREP: PR-CANARY-01 Remediation — dispatch events + fail-closed framing

---

## §0 Repo Profile

- **Languages:** Python 3.12+ (3.13.1 installed)
- **Test command:** `./.venv/bin/python -m pytest tests/ apps/ packages/ -v`
- **Lint command:** `ruff check apps/ packages/ tests/ scripts/ --fix` and `ruff format apps/ packages/`
- **Typecheck command:** `cd apps/web && npx tsc --noEmit` (TS only; not touched by this PR)
- **Build / compile:** `./.venv/bin/python -m compileall apps packages`
- **Migration policy:** `docs/MIGRATION_POLICY.md`. **No migration in this PR.**
- **Coding-log convention:** `coding-logs/<timestamp> Coding Log (<slug>).md`
  with pointer at `.codex/coding-log.current`
- **Coding log:** `coding-logs/2026-08-06-10-00-00 Coding Log (pr-canary-01-remediation).md`
- **Repo ownership:** ours
- **Runtime ownership:** ours
- **Disposition:** production

### MUST NOT list (from CLAUDE.md)

- MUST use Python type hints on all function signatures
- MUST NOT commit secrets, API keys, `.env` files, or credentials
- MUST NOT let crawler workers own product state
- MUST NOT push directly to `main` branch

### Quality gates

```bash
ruff check apps/ packages/ tests/ scripts/
./.venv/bin/python -m compileall apps packages
./.venv/bin/python -m pytest tests/phase1/test_structured_logging.py tests/phase1/test_api_discovery_spawn.py tests/phase2/test_immediate_discover.py tests/phase2/test_discovery_dispatch.py tests/phase3/test_discovery_cancellation_poll.py tests/phase3/test_crawler_agent_runtime.py -v
```

---

## §1 Goal / Non-Goals

**Goal:** Fix two review findings from PR-CANARY-01 (#199): (1) wire `make_event`
calls into `dispatch_cancellable()` so structured events actually appear in the
per-run log at dispatch start/finish/failure, and (2) make `_decode_framed_or_fallback_result`
fail-closed when frame markers are present but the JSON between them is invalid.

**Non-Goals:**

- No change to any other function in the observability package
- No change to the executor (`discovery_dispatch.py`) — events are already wired there
- No change to the worker (`main.py`) — frame production is correct
- No database migration
- No new dependencies
- No change to crawl decisions or retry classification
- Findings 1, 3, 4 from the review (stream ordering, unbounded logs, raw-log redaction) are deferred to separate PRs

---

## §2 Requirements — `R1..R3`

| ID | Requirement |
|----|-------------|
| R1 | `dispatch_cancellable()` writes a `dispatch_started` event to `log_handle` after the log file is opened and before the subprocess spawns. The event includes `run_id`, `owner_pid`, `execution_backend="subprocess"`, and `release_sha` (from `os.environ.get("EGP_RELEASE_SHA")`). |
| R2 | `dispatch_cancellable()` writes a `dispatch_finished` event to `log_handle` on the success path (after metrics emission) and `dispatch_failed` events on each failure path (lease cancellation, timeout, spawn error, generic exception). Failed events include `reason` and the child PID when available. |
| R3 | `_decode_framed_or_fallback_result` returns `None` (fail-closed) when both `RESULT_FRAME_BEGIN` and `RESULT_FRAME_END` are present but the content between them is not a valid JSON dict. Reverse-scan fallback only activates when no frame markers exist at all. |

---

## §3 Change Contract — `F1..F2`

| ID | Path | Action | Anchor (fn/class/region) | New exports | Purpose |
|----|------|--------|--------------------------|-------------|---------|
| F1 | `apps/api/src/egp_api/services/discovery_worker_dispatcher.py` | MODIFY | import block L54-58; `dispatch_cancellable()` L825-1099; `_decode_framed_or_fallback_result()` L546-562 | — | Add `make_event` import; add 4 event writes to dispatch lifecycle; fix fail-open in frame decoder |

---

## §4 Function Contracts

```
FN1  (modification) dispatch_cancellable() — add event writes
     File:        F1, method on SubprocessDiscoveryDispatcher
     Changes:     4 new calls to make_event(), each written to log_handle as
                  encoded bytes + newline. All writes are guarded by
                  `if log_handle is not None`. Events are best-effort (never
                  change crawl outcome per R7 from the original DREP).
     Event sites:
       1. dispatch_started: after log_handle opened (L881), before Popen (L921)
       2. dispatch_finished: after _emit_discovery_run_metrics (L1012)
       3. dispatch_failed: in each except block (lease L1013, timeout L1027,
          spawn L1059, generic L1061)
     Post:        per-run log contains structured events at dispatch boundaries.
     Invariants:  events go to log_handle only, NEVER to stdout/stderr.
                  Failure to write an event is swallowed (R7 fail-open for
                  logging, fail-closed for results).
```

```
FN2  (modification) _decode_framed_or_fallback_result() — fail-closed
     File:        F1, module-level function
     Changes:     When both BEGIN and END markers are found but the content
                  between them is not a valid JSON dict (either JSONDecodeError
                  or not isinstance dict), return None instead of falling
                  through to _decode_discovery_worker_result.
     Pre:         unchanged
     Post:        markers present + invalid content → None (fail-closed);
                  no markers → reverse-scan fallback (unchanged);
                  markers present + valid dict → return dict (unchanged).
     Invariants:  never raises.
```

---

## §5 Test Plan — `T1..T3`

```
T1   test_dispatch_events_written_to_log_handle
     File:      tests/phase1/test_structured_logging.py
     Covers:    R1, R2
     Type:      unit (monkeypatch + FakeProcess, same pattern as T9)
     Arrange:   create a FakeProcess that returns a valid framed discover result
                on stdout with returncode=0. Monkeypatch subprocess.Popen.
                Use tmp_path for artifact_root so log_handle is created.
     Act:       call spawner(tenant_id=..., keyword=...)
     Assert:    read the worker.log file; parse lines as JSON; find at least
                one event with "event"="dispatch_started" containing "run_id",
                "owner_pid", "execution_backend"="subprocess"; find at least
                one event with "event"="dispatch_finished".
     RED-proof: fails before make_event calls are added because no structured
                JSON events exist in the log file — only the worker's raw
                stdout. After adding the calls, the events appear.
     Fixtures:  monkeypatch, tmp_path
```

```
T2   test_dispatch_failed_event_on_nonzero_exit
     File:      tests/phase1/test_structured_logging.py
     Covers:    R2
     Type:      unit (monkeypatch + FakeProcess)
     Arrange:   create a FakeProcess with returncode=1 and no valid result on
                stdout (triggers WORKER_EXIT_NONZERO). Monkeypatch subprocess.Popen.
     Act:       call spawner() and catch DiscoverySpawnError
     Assert:    read worker.log; find an event with "event"="dispatch_failed"
                and "reason" field present.
     RED-proof: fails before make_event calls are added because no
                dispatch_failed event exists in the log. After implementation,
                the event is written before the exception propagates.
     Fixtures:  monkeypatch, tmp_path
```

```
T3   test_framed_result_fails_closed_on_malformed_content
     File:      tests/phase1/test_structured_logging.py
     Covers:    R3
     Type:      unit (pure function)
     Arrange:   build stdout with RESULT_FRAME_BEGIN + "not valid json{{{" +
                RESULT_FRAME_END, followed by a valid JSON dict as the last line
     Act:       call _decode_framed_or_fallback_result(stdout)
     Assert:    returns None (NOT the last-line dict from the reverse-scan)
     RED-proof: fails before the fix because the current code falls through
                to reverse-scan and returns the last-line dict. After the fix,
                returns None because markers are present but content is invalid.
     Fixtures:  none
```

---

## §6 Traceability Matrix

| Req | Tests | Files | Slice |
|-----|-------|-------|-------|
| R1  | T1 | F1 | S1 |
| R2  | T1, T2 | F1 | S1 |
| R3  | T3 | F1 | S1 |

Every R has ≥1 T; every T maps to ≥1 R.

---

## §7 Wiring Verification

| New component | Entry point (runtime caller) | Registration site | Schema/table |
|---|---|---|---|
| `make_event()` calls in `dispatch_cancellable()` | `SubprocessDiscoveryDispatcher.dispatch_cancellable()` L825 → called by `dispatch()` L822, called by `DiscoveryDispatchProcessor` | already imported; adding to import list at L54 | — |
| `_decode_framed_or_fallback_result()` behavior change | same call site at L956 in `dispatch_cancellable()` | already wired | — |

No new components are created. Both changes modify existing wired code.

---

## §8 Slice Plan

| ID | Scope (F/T ids) | Owner | Stop line | Oracle | Done when |
|----|-----------------|-------|-----------|--------|-----------|
| S1 | F1, T1, T2, T3 | **Claude** | — (Q3: modifies dispatcher core dispatch lifecycle and result-extraction security boundary) | T1-T3 green + all 9 existing T1-T9 green + all do-not-touch tests green + ruff clean | All 12 tests green, lint clean, compileall clean |

Single slice, Claude-owned. The dispatch lifecycle and frame-decoder changes are
security-adjacent (tenant log integrity, result-extraction correctness) and cross
the dispatcher's core control flow — not delegatable.

---

## §9 Risks, Rollout, Rollback

| Risk | Trigger | Blast radius | Gate | Rollback |
|------|---------|-------------|------|----------|
| Event write fails and swallows exception | log_handle.write raises | Dispatch would fail if exception propagated | Wrap in try/except per R7 (logging is best-effort) | Remove event writes |
| Fail-closed framing rejects a valid result | Bug in the marker detection | Crawl result lost, dispatch reports WORKER_RESULT_MISSING | T2 from original suite tests framed extraction; T3 tests malformed; T3 from original suite tests no-marker fallback | Revert the `return None` line |

**Rollout:** Both changes are observability-only. Dispatch events are additive to the log.
Fail-closed framing is strictly safer than fail-open (it prevents a malformed frame from
tricking the reverse-scan into returning garbage).

---

## §10 Do-Not-Touch List

### Test files (must stay green, must not be modified by this remediation)

All files from the original PR-CANARY-01 do-not-touch list remain in force.
The existing T1-T9 tests in `tests/phase1/test_structured_logging.py` are
**extended** (new tests added at the end), never modified.

### Source files

- `packages/observability/src/egp_observability/logging.py` — no changes needed
- `packages/observability/src/egp_observability/__init__.py` — no changes needed
- `apps/worker/src/egp_worker/main.py` — frame production unchanged
- `apps/api/src/egp_api/executors/discovery_dispatch.py` — executor events already correct
