# DREP: PR-CANARY-01 — correlated, bounded runtime evidence

> **Synthesized** from the draft DREP + Codex adversarial review (12 findings,
> 6 HIGH, 6 MEDIUM; all accepted or partially accepted). Changes from the
> draft are marked with **[Codex#N]** where the Codex finding drove the change.

---

## §0 Repo Profile

- **Languages:** Python 3.12+ (3.13.1 installed)
- **Test command:** `./.venv/bin/python -m pytest tests/ apps/ packages/ -v`
- **Lint command:** `ruff check apps/ packages/ tests/ scripts/ --fix` and `ruff format apps/ packages/`
- **Typecheck command:** `cd apps/web && npx tsc --noEmit` (TS only; not touched by this PR)
- **Build / compile:** `./.venv/bin/python -m compileall apps packages`
- **Lock check:** — (no `uv lock --check` configured for this PR; no new deps)
- **Migration policy:** `docs/MIGRATION_POLICY.md`. **No migration in this PR.**
- **Coding-log convention:** `coding-logs/<timestamp> Coding Log (<slug>).md`
  with pointer at `.codex/coding-log.current`
- **Coding log:** `coding-logs/2026-08-05-18-30-00 Coding Log (pr-canary-01-correlated-runtime-evidence).md`
- **Repo ownership:** ours
- **Runtime ownership:** ours
- **Disposition:** production

### MUST NOT list (from CLAUDE.md)

- MUST use Python type hints on all function signatures
- MUST NOT commit secrets, API keys, `.env` files, or credentials
- MUST NOT use `any` type in TypeScript without justification
- MUST NOT let crawler workers own product state
- MUST NOT push directly to `main` branch
- MUST NOT store browser profiles or temp downloads inside OneDrive-synced directories

### Quality gates

```bash
ruff check apps/ packages/ tests/ scripts/
./.venv/bin/python -m compileall apps packages
./.venv/bin/python -m pytest tests/phase1/test_structured_logging.py tests/phase1/test_api_discovery_spawn.py tests/phase2/test_immediate_discover.py tests/phase2/test_discovery_dispatch.py tests/phase3/test_discovery_cancellation_poll.py tests/phase3/test_crawler_agent_runtime.py -v
```

---

## §1 Goal / Non-Goals

**Goal:** Make the dispatcher's subprocess child output diagnosable — correlated,
bounded, and redacted — without changing any crawl decision, retry classification,
or outcome. This is the observability prerequisite for the fault-injection and
canary evidence that PR-CANARY-02 through PR-CANARY-07 depend on.

**Non-Goals:**

- No database migration
- No change to crawl decisions, project state, retry classification, or document persistence
- No change to the worker's business logic
- No new API routes or response shapes
- No change to Prometheus metrics (PR-CANARY-07)
- **[Codex#1,#2,#3]** No stream merging at the OS level — stdout and stderr stay separate to preserve entitlement-denial routing (`_parse_non_retriable_error` scans stderr at L490)
- **[Codex#4]** No per-run log rotation — the run-log API (`run_service.py`) reads the canonical `worker.log` by exact path; rotating it would break the API
- **[Codex#8]** No structured logging for the `agent_runtime.py` process — deferred to PR-CANARY-06
- No automatic log shipping or remote log aggregation
- No Cloudflare/Turnstile bypass or `egp_crawler.py` refactoring

---

## §2 Requirements — `R1..R7`

| ID | Requirement |
|----|-------------|
| R1 | A structured log event function produces UTC-timestamped single-line JSON with a stable vocabulary of event names. Context fields include run_id, discovery_job_id (when known), owner PID, child PID, execution_backend, and `EGP_RELEASE_SHA` (from env, never from `git`). None-valued fields are omitted. The function returns a string; it is never printed to stdout in the executor's one-shot mode. **[Codex#9]** Events go to `log_handle` (per-run log) or `sys.stderr` — NEVER to `sys.stdout` in any code path where stdout carries machine-readable results. |
| R2 | The per-run log file (`worker.log`) continues to receive stderr during execution (via `_communicate_with_cancellation` L343, piped to `log_handle`) and stdout appended after exit (via `_drain_worker_stdout` L593). The existing separate-stream architecture is unchanged. Structured events are written to the per-run `log_handle` alongside the child's output. **[Codex#1,#2]** |
| R3 | The discover command's final JSON result is wrapped in frame delimiters on stdout. The dispatcher extracts framed results first, falling back to the existing reverse-line-scan (`_decode_discovery_worker_result` L539). The framed JSON line is a standalone dict (backward-compatible). Truncated or malformed frames trigger fallback. **[Codex#7]** Non-discover commands (`noop`, `close_check`, `document_ingest`, `timeout_evaluate`, `run_scheduled_discovery`) continue to emit bare JSON — framing is discover-only. Mixed-version deployments are compatible in both directions: old-dispatcher/new-worker (reverse-scan finds the framed line), new-dispatcher/old-worker (fallback to reverse-scan). **[Codex#6]** A truncated frame (BEGIN found but END missing due to 65KB `_read_log_tail` limit at L1246) is treated as absent and triggers fallback — this is an existing constraint, not a new one. |
| R4 | The stderr preview function uses tail-oriented bounded extraction (last N bytes, not first N bytes) after shared redaction of secrets/credentials/PII patterns. **[Codex#10]** Accepts `bytes | str | None`. The actual terminal exception is preserved rather than an initial Node warning. The profile-state write paths at L247 and L273 (which pass short error strings with `limit=300`) also switch to the tail preview — identical output for short strings. |
| R5 | The aggregate native watcher log (`~/Library/Logs/egp/crawl.log`) is rotated using copytruncate semantics at dispatcher startup. Keeps at most N rotated copies. Rotation never deletes files that don't match the rotation naming pattern. **[Codex#4]** Per-run log files (`worker.log`) are NOT rotated. |
| R6 | `EGP_RELEASE_SHA` is available to the dispatcher process via `os.environ`. **[Codex#5]** The env var is documented in `.env.remotecrawl.example`, `docker-compose.yml`, and `docker-compose-localdev.yml`. The child inherits it automatically via the existing `env={**os.environ, ...}` pattern. It is optional: None when unset. |
| R7 | All changes are fail-open with respect to crawling: a logging/rotation/redaction/framing failure must never change the crawl outcome, retry classification, or dispatch result. |

---

## §3 Change Contract — one row per file, `F1..F10`

| ID | Path | Action | Anchor (fn/class/region) | New exports | Purpose |
|----|------|--------|--------------------------|-------------|---------|
| F1 | `packages/observability/src/egp_observability/logging.py` | CREATE | — | `make_event`, `redact_preview`, `tail_bounded_preview`, `rotate_log_copytruncate`, `RESULT_FRAME_BEGIN`, `RESULT_FRAME_END` | Structured logging primitives |
| F2 | `packages/observability/src/egp_observability/__init__.py` | MODIFY | top-level re-exports L1-41 | re-export F1 names | Package wiring |
| F3 | `apps/api/src/egp_api/services/discovery_worker_dispatcher.py` | MODIFY | `_stderr_preview` L475-487, `_decode_discovery_worker_result` call at L946, `dispatch_cancellable` ~L815 | — | Use `tail_bounded_preview`, add `_decode_framed_or_fallback_result`, write structured events to log_handle |
| F4 | `apps/api/src/egp_api/executors/discovery_dispatch.py` | MODIFY | `main` L650-660 | — | Rotate aggregate log at startup; read `EGP_RELEASE_SHA`; write structured start/stop events to stderr (not stdout) |
| F5 | `apps/worker/src/egp_worker/main.py` | MODIFY | `main` L320-333 (discover print paths only) | — | Wrap discover command's final JSON in frame delimiters; noop/other commands unchanged |
| F6 | `deploy/.env.remotecrawl.example` | MODIFY | env vars list | — | Add `EGP_RELEASE_SHA` with documentation comment |
| F7 | `docker-compose.yml` | MODIFY | discovery-executor environment block | — | Add `EGP_RELEASE_SHA` passthrough |
| F8 | `docker-compose-localdev.yml` | MODIFY | discovery-executor environment block | — | Add `EGP_RELEASE_SHA` passthrough |
| F9 | `scripts/install_launchd.sh` | MODIFY | `cmd_install` help text | — | Document that `EGP_RELEASE_SHA` should be set in `.env.remotecrawl` |
| F10 | `docs/OBSERVABILITY.md` | MODIFY | end of file | — | Document structured logging, frame protocol, redaction, rotation |

---

## §4 Function Contracts — `FN1..FN7`

```
FN1  make_event(
         event: str,
         *,
         run_id: str | None = None,
         job_id: str | None = None,
         owner_pid: int | None = None,
         child_pid: int | None = None,
         execution_backend: str | None = None,
         release_sha: str | None = None,
         **extra: object,
     ) -> str
     File:        F1
     Does:        Build a single-line JSON string with UTC timestamp, event name,
                  and all non-None context fields. Extra values are str()-coerced.
     Pre:         event is a non-empty string.
     Post:        returns a parseable JSON string; "ts" field is UTC ISO-8601;
                  no newlines in the output; None-valued fields are omitted;
                  keys are sorted for deterministic output.
     Errors:      never raises; malformed extra values are str()-coerced.
     Invariants:  output is always a single valid JSON line; the function is
                  pure (no I/O, no side effects).
     Sink:        [Codex#9] the CALLER decides where to write it. In the
                  dispatcher (F3), events go to log_handle. In the executor (F4),
                  events go to sys.stderr. MUST NEVER be printed to stdout in
                  the executor's one-shot mode (would corrupt the machine-readable
                  DiscoveryOneShotSummary) or in the worker's result path (would
                  corrupt the JSON stdout protocol).
     Notes:       ≤25 lines.
```

```
FN2  redact_preview(text: str) -> str
     File:        F1
     Does:        Replace known secret patterns with "[REDACTED]".
                  Patterns: database URL passwords (postgresql://user:PASS@host),
                  SUPABASE_SERVICE_ROLE_KEY values, bearer tokens, basic auth.
                  Compiled at module level.
     Pre:         text is a string (possibly empty).
     Post:        returns text with secrets replaced; len(result) <= len(text);
                  never raises.
     Errors:      none.
     Invariants:  idempotent; conservative (false negatives acceptable;
                  false positives on real project data are not).
     Notes:       ≤25 lines.
```

```
FN3  tail_bounded_preview(
         text: bytes | str | None,
         *,
         limit: int = 2000,
     ) -> str | None
     File:        F1
     Does:        Return the last `limit` characters of text after redaction.
                  Drop-in replacement for _stderr_preview (same signature
                  contract: accepts bytes | str | None per [Codex#10]).
     Pre:         text may be bytes, str, or None. Bytes are decoded utf-8
                  with errors="replace".
     Post:        returns None for None/empty input; otherwise the redacted
                  tail of at most `limit` characters. Prepends "..." if
                  truncated.
     Errors:      never raises.
     Invariants:  len(result) <= limit + 3 (for "..." prefix) when truncated.
                  Short strings (len <= limit) are returned in full after
                  redaction — identical to _stderr_preview for small inputs.
                  The profile-state call sites at L247 and L273 pass short
                  error strings with limit=300 — output is identical.
     Notes:       ≤15 lines.
```

```
FN4  rotate_log_copytruncate(
         path: Path,
         *,
         max_bytes: int = 50_000_000,
         max_files: int = 3,
     ) -> bool
     File:        F1
     Does:        If path exists and exceeds max_bytes, copies it to path.1
                  (shifting existing .1→.2 etc.), then truncates the original
                  in place (same inode, so launchd's open FD keeps working).
                  Removes rotated copies beyond max_files.
     Pre:         path's parent directory exists.
     Post:        returns True if rotation happened, False otherwise.
                  Only files matching the exact rotation pattern (path.N where
                  N is an integer) are affected. NEVER touches files that don't
                  match the pattern. NEVER deletes browser profiles, worker.log
                  files, or operational manifests.
     Errors:      never raises; rotation failures are swallowed (the caller
                  continues with the potentially-large log file). [R7]
     Invariants:  copytruncate preserves the inode; launchd's open FD remains
                  valid. The original file is empty after rotation, not deleted.
     Target:      [Codex#4] ONLY the aggregate watcher log
                  (~/Library/Logs/egp/crawl.log). Per-run logs (worker.log)
                  are NEVER rotated — the run-log API reads them by exact path.
     Notes:       ≤30 lines.
```

```
FN5  RESULT_FRAME_BEGIN: Final[str] = "---EGP_RESULT_BEGIN---"
     RESULT_FRAME_END: Final[str] = "---EGP_RESULT_END---"
     File:        F1
     Does:        Sentinel strings for framing the worker's JSON result on stdout.
                  Shared constant source for both producer (worker F5) and consumer
                  (dispatcher F3).
     Invariants:  sentinels must be unlikely to appear in normal program output;
                  the JSON line between them is a standalone dict (same contract
                  as the existing reverse-scan expects).
     Mixed-version: [Codex#11] old-dispatcher/new-worker — the framed JSON line
                  is still the last dict-valued JSON line on stdout, so the existing
                  reverse-scan finds it. new-dispatcher/old-worker — no frame
                  markers, so _decode_framed_or_fallback_result falls back to
                  the reverse-scan. Both directions produce correct results.
```

```
FN6  _decode_framed_or_fallback_result(
         stdout: bytes | str | None,
     ) -> dict[str, object] | None
     File:        F3 (module-level function)
     Does:        Scan for the LAST complete frame (RESULT_FRAME_BEGIN ... JSON ...
                  RESULT_FRAME_END). Extract and parse the JSON between them.
                  If no complete frame is found (no markers, truncated frame,
                  malformed content), fall back to the existing
                  _decode_discovery_worker_result (reverse-line-scan at L539).
     Pre:         stdout is the tail of the child's output (up to 65KB via
                  _read_log_tail at L1246).
     Post:        returns parsed dict or None.
     Errors:      never raises; parse failures return None.
     Invariants:  [Codex#6,#11] backward-compatible with unframed output. Uses
                  the LAST complete frame, not the first. A truncated frame
                  (BEGIN found but END missing due to 65KB tail) is treated as
                  absent and triggers fallback. The fallback path is the EXISTING
                  _decode_discovery_worker_result — no behavioral change when
                  no frame markers are present.
     Notes:       ≤20 lines.
```

```
FN7  _emit_framed_result(result: dict) -> None
     File:        F5 (module-level function, called only for discover command)
     Does:        Print RESULT_FRAME_BEGIN, the JSON result (single line),
                  and RESULT_FRAME_END to stdout. The JSON line itself is
                  identical to the current output (backward-compatible).
     Pre:         result is a JSON-serializable dict; command is "discover".
     Post:        three lines printed to stdout. [Codex#7] Non-discover commands
                  (noop, close_check, etc.) continue to print bare JSON.
     Errors:      never raises; if print fails, the JSON has already been
                  written by the caller's fallback path.
     Scope:       ONLY for the discover command. Both the discover-success path
                  (L333) and the discover-failed path (L326, exit 1) are framed
                  so the dispatcher can distinguish a structured failure from a crash.
     Notes:       ≤10 lines.
```

---

## §5 Test Plan — `T1..T9`

```
T1   test_make_event_produces_utc_timestamped_single_line_json
     File:      tests/phase1/test_structured_logging.py
     Covers:    R1
     Type:      unit (pure function, no I/O)
     Arrange:   —
     Act:       call make_event("dispatch_started", run_id="r1", owner_pid=42,
                release_sha="abc123")
     Assert:    result parses as JSON; has "ts" key with UTC ISO-8601
                (ends with +00:00 or Z); has "event"="dispatch_started";
                has "run_id"="r1", "owner_pid"=42, "release_sha"="abc123";
                no "job_id" key (was None); output has no newlines
     RED-proof: fails with ImportError (make_event absent) before F1 exists;
                after a naive impl returning unstructured text, fails on
                json.loads.
     Fixtures:  none
```

```
T2   test_framed_result_is_extracted_before_fallback_reverse_scan
     File:      tests/phase1/test_structured_logging.py
     Covers:    R3
     Type:      unit (pure function)
     Arrange:   build stdout bytes: noise lines, then FRAME_BEGIN + valid JSON
                + FRAME_END, then a DIFFERENT valid JSON dict as the last line
     Act:       call _decode_framed_or_fallback_result(stdout)
     Assert:    returns the framed JSON dict (not the last-line dict)
     RED-proof: fails with ImportError before FN6 exists; a naive impl that
                only does reverse-scan returns the wrong (last-line) JSON dict.
     Fixtures:  none
```

```
T3   test_framed_result_falls_back_to_reverse_scan_when_no_frame
     File:      tests/phase1/test_structured_logging.py
     Covers:    R3
     Type:      unit (pure function)
     Arrange:   build stdout bytes with only plain JSON on the last line (no
                frame markers at all)
     Act:       call _decode_framed_or_fallback_result(stdout)
     Assert:    returns the last-line JSON dict (backward compatibility)
     RED-proof: fails with ImportError before FN6 exists; after a frame-only
                impl that returns None when no frame, fails with
                AssertionError.
     Fixtures:  none
```

```
T4   test_tail_bounded_preview_preserves_terminal_exception
     File:      tests/phase1/test_structured_logging.py
     Covers:    R4
     Type:      unit (pure function)
     Arrange:   build a 5000-char string: 4000 chars of Node warnings followed
                by a 1000-char Python traceback ending with "RuntimeError: boom"
     Act:       call tail_bounded_preview(text, limit=2000)
     Assert:    result ends with "RuntimeError: boom"; result starts with "...";
                len(result) <= 2003
     RED-proof: fails with ImportError before FN3 exists; the old
                _stderr_preview (first-500-char) would return the Node
                warnings, failing the ends-with assertion.
     Fixtures:  none
```

```
T5   test_redact_preview_removes_known_secret_patterns
     File:      tests/phase1/test_structured_logging.py
     Covers:    R4
     Type:      unit (pure function)
     Arrange:   build text containing "postgresql://egp:secret_password@host/db",
                "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSJ9.sig",
                and "Bearer eyJhbGciOi..."
     Act:       call redact_preview(text)
     Assert:    "secret_password" not in result; "eyJhbGciOi" not in result;
                "[REDACTED]" appears in result; non-secret portions preserved
                (e.g., "postgresql://" still present)
     RED-proof: fails with ImportError before FN2 exists; after a passthrough
                impl, fails because "secret_password" is still present.
     Fixtures:  none
```

```
T6   test_rotate_log_copytruncate_preserves_inode_and_bounds_copies
     File:      tests/phase1/test_structured_logging.py
     Covers:    R5
     Type:      integration (real filesystem via tmp_path)
     Arrange:   write 200 bytes to a file; call rotate_log_copytruncate with
                max_bytes=100, max_files=2
     Act:       check the result and filesystem state
     Assert:    returns True; original file exists and is empty (0 bytes);
                .1 copy exists with the 200 bytes; original inode unchanged
                (stat before and after)
     RED-proof: fails with ImportError before FN4 exists; after an impl
                that renames instead of copytruncate, the inode changes.
     Fixtures:  tmp_path
```

```
T7   test_make_event_omits_none_fields_and_sorts_keys
     File:      tests/phase1/test_structured_logging.py
     Covers:    R1, R6
     Type:      unit (pure function)
     Arrange:   —
     Act:       call make_event("worker_started", release_sha="abc123",
                job_id=None, child_pid=None)
     Assert:    parsed JSON has "release_sha"="abc123"; "job_id" key absent;
                "child_pid" key absent; keys are sorted
     RED-proof: fails with ImportError before F1; after an impl that includes
                all fields, fails on "job_id" presence assertion.
     Fixtures:  none
```

```
T8   test_rotation_never_removes_non_matching_files
     File:      tests/phase1/test_structured_logging.py
     Covers:    R5, R7
     Type:      integration (real filesystem via tmp_path)
     Arrange:   create a directory with a .json profile state file, a
                subdirectory named "browser-profile", and the log file
                exceeding max_bytes; set max_files=1
     Act:       call rotate_log_copytruncate; then write more data and
                rotate again (this should remove .2 since max_files=1)
     Assert:    the .json file still exists; the "browser-profile" subdirectory
                still exists; only .1 rotation file exists (the .2 was removed
                but nothing else)
     RED-proof: fails if rotation uses glob("*") or rmtree; after a correct
                impl with pattern-matched deletion, passes.
     Fixtures:  tmp_path
```

```
T9   test_dispatcher_extracts_framed_result_from_fake_worker
     File:      tests/phase1/test_structured_logging.py
     Covers:    R3, R7 (wiring verification)
     Type:      unit (uses monkeypatch + FakeProcess)
     Arrange:   [Codex#12] create a FakeProcess that emits stdout with logging
                noise + RESULT_FRAME_BEGIN + valid discover result JSON +
                RESULT_FRAME_END + more noise; returncode=0.
                Monkeypatch subprocess.Popen.
     Act:       call spawner(tenant_id=..., keyword=...)
     Assert:    the dispatcher does NOT raise (result was extracted via frame);
                the spawner completes successfully despite noise around the frame
     RED-proof: fails with NameError before FN6 is wired into the dispatcher;
                after wiring, passes because framed extraction ignores noise.
                Without the wiring change (still calling _decode_discovery_worker_result),
                the noise "last JSON line" could be a non-result dict and would
                fail validation.
     Fixtures:  monkeypatch, tmp_path
```

---

## §6 Traceability Matrix

| Req | Tests | Files | Slice |
|-----|-------|-------|-------|
| R1  | T1,T7 | F1,F2 | S1 |
| R2  | T9 (wiring) | F3 | S2 |
| R3  | T2,T3,T9 | F1,F3,F5 | S1,S2 |
| R4  | T4,T5 | F1,F3 | S1,S2 |
| R5  | T6,T8 | F1,F4 | S1,S3 |
| R6  | T7 | F1,F4,F6,F7,F8 | S1,S3 |
| R7  | T8,T9 | F1,F3,F4 | S1,S2,S3 |

Every R has ≥1 T; every T maps to ≥1 R.

---

## §7 Wiring Verification

| New component | Entry point (runtime caller) | Registration site | Schema/table |
|---|---|---|---|
| `make_event()` | `SubprocessDiscoveryDispatcher.dispatch_cancellable()` F3 ~L815: writes events to `log_handle` | imported from `egp_observability.logging` | — |
| `make_event()` | `discovery_dispatch.main()` F4 ~L657: writes events to `sys.stderr` (NOT stdout, preserving one-shot contract) | imported from `egp_observability.logging` | — |
| `redact_preview()` | called by `tail_bounded_preview()` inside F1 | internal to F1 | — |
| `tail_bounded_preview()` | replaces `_stderr_preview()` calls in F3 at L978, L1030 (subprocess stderr) and L247, L273 (profile-state error strings) | imported from `egp_observability.logging` | — |
| `rotate_log_copytruncate()` | `discovery_dispatch.main()` F4 at startup, before the dispatch loop | imported from `egp_observability.logging` | — |
| `RESULT_FRAME_BEGIN/END` | `_emit_framed_result()` in F5 (producer) and `_decode_framed_or_fallback_result()` in F3 (consumer) | imported from `egp_observability.logging` | — |
| `_decode_framed_or_fallback_result()` | `dispatch_cancellable` F3 ~L946 (replaces direct call to `_decode_discovery_worker_result`; delegates to existing `_decode_discovery_worker_result` for fallback) | module-level function in F3 | — |
| `_emit_framed_result()` | `main()` in F5 L326 (discover-failed) and L333 (discover-success); replaces raw `print(json.dumps(...))` | module-level function in F5 | — |
| `EGP_RELEASE_SHA` env var | read by `discovery_dispatch.main()` from `os.environ`; inherited by child subprocess via existing `env={**os.environ, ...}` pattern | documented in F6, F7, F8 | — |

---

## §8 Slice Plan — `S1..S3`

| ID | Scope (F/T ids) | Owner | Stop line | Oracle | Done when |
|----|-----------------|-------|-----------|--------|-----------|
| S1 | F1,F2,T1-T8 | **DeepSeek** | SL-2 (Q2: creates new module in observability package, crosses package boundary for re-exports) | T1-T8 green + ruff clean + compileall | All 8 tests green, `egp_observability.logging` importable, ruff clean |
| S2 | F3,F5,T9 | **Claude** | — (Q3: modifies dispatcher core result-extraction + preview path; **[Codex#1]** security: redaction of secrets in preview output; **[Codex#3]** wiring to entitlement-denial routing via `_parse_non_retriable_error` must be preserved — stderr stays separate) | T9 + all 17 existing spawn tests + all 15 existing dispatch tests + all 3 cancellation-poll tests + all 19 agent-runtime tests green | Framed extraction works, tail preview wired, existing tests pass |
| S3 | F4,F6,F7,F8,F9,F10 | **DeepSeek** | SL-1 (Q1: mechanical env-read, config additions, docs) | Existing dispatch executor tests green + compileall | Release SHA plumbed, aggregate log rotation at startup, docs updated |

**Dependency order:** S1 → S2 → S3 (S2 uses S1's exports; S3 uses S1 and assumes S2's wiring)

---

## §9 Risks, Rollout, Rollback

| Risk | Trigger | Blast radius | Gate | Rollback |
|------|---------|-------------|------|----------|
| Tail preview changes profile-state error text | Profile-warm failure writes a different preview | Operator sees different error in profile state JSON | Profile-state calls use short error strings (< 300 chars), so head = tail; verified at L247 (limit=300) and L273 (limit=300) | No rollback needed; short strings are identical |
| [Codex#7] Framing breaks noop/non-discover tests | FN7 wraps all commands instead of just discover | test_worker_entrypoint.py and test_observability_metrics.py fail | FN7 scoped to discover only (guarded by `command == "discover"` check); T9 wiring test; test_worker_entrypoint.py in do-not-touch | Remove framing for non-discover commands |
| [Codex#4] Rotation deletes wrong files or per-run logs | Bug in copytruncate pattern matching, or rotation targets worker.log | Browser profile or run log deleted; run-log API returns 404 | T8 explicitly tests non-log file preservation; T6 tests inode preservation; rotate_log_copytruncate is called ONLY on aggregate log path, NEVER on per-run logs | Rotation is best-effort; disable by setting max_bytes very high |
| Old dispatcher + new worker (frame markers in stdout) | Deploy worker before dispatcher | Old reverse-scan sees the framed JSON as the last dict line | The framed JSON is a valid standalone dict on its own line (same as current output) | No action needed; backward-compatible by construction |
| New dispatcher + old worker (no frame markers) | Deploy dispatcher before worker | FN6 falls back to reverse-scan | T3 explicitly tests this case | Fallback is the existing behavior |
| [Codex#5] EGP_RELEASE_SHA missing from env | Deploy before adding to env config | make_event outputs `release_sha: null` | release_sha is optional; None omitted from output | No action needed; purely informational |
| [Codex#6] Framed result split by 65KB tail truncation | Very long stdout (> 65KB) | RESULT_FRAME_BEGIN present but RESULT_FRAME_END missing | FN6 treats truncated frame as absent → fallback to reverse-scan | Existing behavior; 65KB limit is pre-existing constraint at L1246 |

**Rollout:** All changes deploy dark. Log format changes are observability-only. The framing is additive. `EGP_RELEASE_SHA` is optional (None when unset). No crawl decisions change.

---

## §10 Do-Not-Touch List

### Existing test files (must stay green, must not be modified)

- `tests/phase1/test_api_discovery_spawn.py` (17 tests) — existing spawn tests
- `tests/phase1/test_worker_entrypoint.py` — worker stdout contract (framing must not break noop/close_check paths)
- `tests/phase1/test_projects_and_runs_api.py` — run-log API reads `worker.log` by exact path
- **[Codex#3]** `tests/phase2/test_immediate_discover.py` — tests stderr preview + entitlement_denied routing
- `tests/phase2/test_discovery_dispatch.py` (15 tests) — dispatch processor tests
- `tests/phase2/test_dispatcher_event_loop.py` (3 tests) — async loop tests
- **[Codex#7]** `tests/phase2/test_observability_metrics.py` — worker metric contract (noop path must not frame)
- `tests/phase2/test_persistent_browser_profile.py` — profile lock/warm tests
- **[Codex#3]** `tests/phase3/test_discovery_cancellation_poll.py` — `_communicate_with_cancellation` tests (stderr piping must be preserved)
- `tests/phase3/test_crawler_agent_runtime.py` (19 tests) — agent runtime tests
- `tests/phase3/test_crawler_agent_shadow_parity.py` — shadow parity tests
- `apps/api/tests/test_browser_isolation.py` — browser isolation FakeProcess
- `apps/api/tests/test_dispatch_trigger_metadata.py` — dispatch trigger tests
- `tests/phase2/test_discovery_executor.py` — executor one-shot stdout contract (make_event must NOT write to stdout here)

### Source files that must not change

- `apps/worker/src/egp_worker/workflows/discover.py` — discovery workflow logic
- `apps/worker/src/egp_worker/browser_discovery.py` — browser logic
- **[Codex#8]** `apps/worker/src/egp_worker/agent_runtime.py` — agent runtime (deferred to PR-CANARY-06)
- `packages/db/src/migrations/` — no migrations
- `packages/observability/src/egp_observability/metrics.py` — metrics unchanged
- `apps/api/src/egp_api/services/run_service.py` — run-log API (reads per-run worker.log by path; rotation must never touch these)

---

## §11 Codex Adversarial Review Dispositions

| # | Severity | Finding summary | Disposition | Action taken in this DREP |
|---|----------|----------------|-------------|---------------------------|
| 1 | HIGH | Merged streams can change entitlement-denial routing | ACCEPTED | Removed all stream-merging; added explicit non-goal; stderr stays separate |
| 2 | HIGH | FN7 (old draft) had no process-lifecycle contract | ACCEPTED | Removed old FN7 (thread-based merger); current FN7 is just _emit_framed_result |
| 3 | HIGH | Do-not-touch conflicts with pipe merger | ACCEPTED | Added test_immediate_discover.py and test_discovery_cancellation_poll.py to do-not-touch |
| 4 | HIGH | RotatingFileWriter targets wrong log model | ACCEPTED | Clarified: only aggregate log rotates; per-run logs NEVER rotate; added run-log API test to do-not-touch |
| 5 | HIGH | Release-SHA propagation incomplete | ACCEPTED | Added to .env.remotecrawl.example, docker-compose.yml, docker-compose-localdev.yml; documented optional |
| 6 | HIGH | Framed result may exceed 65KB tail | ACCEPTED | Documented: truncated frame → fallback; 65KB is pre-existing constraint |
| 7 | MEDIUM | F5 breaks noop/non-discover stdout | ACCEPTED | FN7 scoped to discover-only; test_worker_entrypoint.py and test_observability_metrics.py in do-not-touch |
| 8 | MEDIUM | agent_runtime structured logging scope creep | ACCEPTED | Removed; deferred to PR-CANARY-06; agent_runtime.py in do-not-touch |
| 9 | MEDIUM | make_event has no sink contract | ACCEPTED | Added explicit Sink section to FN1 contract; log_handle in F3, stderr in F4, NEVER stdout |
| 10 | MEDIUM | FN3 doesn't match existing signature | ACCEPTED | FN3 accepts bytes | str | None like original _stderr_preview |
| 11 | MEDIUM | Frame parsing/mixed-version underspecified | ACCEPTED | Clarified: last complete frame; malformed → fallback; mixed-version compatible both directions |
| 12 | MEDIUM | Tests are vacuous primitives | PARTIALLY | Added T9 wiring test exercising full dispatcher path with framed output |
