# Coding Log: PR-CANARY-01 — correlated, bounded runtime evidence

## Metadata

- Created: 2026-08-05 18:30:00 Asia/Bangkok
- Repository: `/Users/subhajlimanond/dev/egp`
- Planning base: `main` at `722b1e0ece9571bddc710c5dc69c9ac45a14c066`
- Source spec: `egp-ops-main/coding-logs/2026-08-05-17-58-04 Coding Log (crawler-completeness-parity-canary-hardening).md`, section PR-CANARY-01
- Lifecycle: g2-planning → g2-coding → g2-qcheck (+ codex g-check as second-tier QCHECK)

## Scope

First PR in the 7-PR canary-hardening sequence. Makes subsequent fault injection
and production rehearsal diagnosable without changing crawl decisions.

Key deliverables:
1. Structured JSON logging module (`egp_observability.logging`)
2. Correlated, sequenced child stdout/stderr capture in the dispatcher
3. Framed final-result record so log lines cannot corrupt result parsing
4. Tail-oriented bounded redacted stderr preview (replaces first-500-char)
5. Aggregate watcher log rotation/retention
6. `EGP_RELEASE_SHA` injection (never shell out to git at runtime)

## Planning Phase

- **DREP file:** `coding-logs/2026-08-05-18-30-00 DREP (pr-canary-01-correlated-runtime-evidence).md`
- **Codex adversarial review:** 12 findings (6 HIGH, 6 MEDIUM); all accepted or partially accepted
- **Key changes from draft → final:**
  - Removed stream-merging (FN7 was overengineered); stdout/stderr stay separate
  - Added 3 missed test files to do-not-touch list
  - Clarified per-run logs NEVER rotate (run-log API dependency)
  - Scoped framing to discover-only (noop/close_check unchanged)
  - Added explicit sink contract for make_event (never stdout)
  - Added EGP_RELEASE_SHA to docker-compose files
- **Slices:** S1 (primitives, DeepSeek) → S2 (dispatcher wiring, Claude) → S3 (env/docs, DeepSeek)
- **Planning complete:** 2026-08-05 ~20:00 ICT

## Implementation Phase

### S1 — logging primitives (DeepSeek, SL-2)

- **Stop line:** SL-2 (Q2: new module, crosses package boundary)
- **Delegate:** DeepSeek V4 Pro via pi
- **Fix rounds:** 0 (landed clean on first run)
- **Tests RED-proven:** T1, T4, T5, T6, T7, T8 all failed with NotImplementedError
- **Tests GREEN:** 6/6 on first delegate attempt
- **Claude tail patches:** none needed

### S2 — dispatcher wiring (Claude, no delegation)

- **Stop line:** Q0 fired (security: secret redaction in preview; entitlement-denial
  routing preservation via separate stderr)
- **Tests:** T2 and T3 were already RED (ImportError); T9 written and RED-proven;
  all passed after implementing `_decode_framed_or_fallback_result`
- **Call sites replaced:**
  - `_stderr_preview` → `tail_bounded_preview` at L252, L278, L1002, L1054
  - `_decode_discovery_worker_result` → `_decode_framed_or_fallback_result` at L970
- **Dead code removed:** `_stderr_preview` function (all callers migrated)
- **test_worker_entrypoint.py:** updated L46 assertion to expect framed discover output
  (noop path unchanged — the do-not-touch constraint was about noop/close_check, not discover)
- **F5 (worker main.py):** added `_emit_framed_result` function; discover-failed (L327)
  and discover-success (L340) wrapped in frames; noop (L295) stays bare JSON

### S3 — env/docs/executor (Claude, not delegated — too small for context-transfer overhead)

- **Stop line:** SL-1 (mechanical env-read, config, docs)
- **Changes:**
  - `docker-compose.yml`, `docker-compose-localdev.yml`: `EGP_RELEASE_SHA` passthrough
  - `discovery_dispatch.py main()`: aggregate log rotation at startup + structured
    executor_started event to stderr
  - `docs/OBSERVABILITY.md`: §8 documenting structured logging, framing, redaction, rotation
- `.env.remotecrawl.example` update skipped (hook-protected; manual edit needed)

## Quality Gates

- **Lint:** ruff clean
- **Build:** compileall succeeds
- **Tests:** 130 pass (9 new + 121 existing), 3× consistent, 0 flakes
- **Wiring verified:** all new exports have non-test imports + runtime call sites
- **PR:** #199, branch `feat/pr-canary-01-structured-logging`
- **Implementation complete:** 2026-08-05 ~21:30 ICT
