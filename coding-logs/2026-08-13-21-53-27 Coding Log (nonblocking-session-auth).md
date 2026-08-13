# Coding Log: Non-blocking Session Authentication

Started: 2026-08-13 21:53:27 +0700
Branch: `fix/nonblocking-session-auth`
Baseline: `e107253aefdfdfb811e8d32ae817dd74f735c86a`
DREP: `coding-logs/2026-08-13-21-53-27 DREP (nonblocking-session-auth).md`

## Planning

- RepoPrompt and independent Terra confirmed the async middleware directly executes a synchronous
  repository read plus unconditional activity write.
- Locked a no-auth-cache design: authoritative read per cookie request in a bounded executor, with
  separate bounded/coalesced best-effort activity maintenance.
- No migration, environment setting, JWT change, worker-token change, or product-code delegation.

## RED

- Added deterministic runtime contracts for event-loop progress during a blocked synchronous lookup,
  retained saturation capacity after timeout, lifecycle ownership, shutdown rejection, queued-work
  cancellation, database failure, activity-scheduler failure, queue overflow, and coalescing without an
  authentication cache.
- Added API/repository contracts for read-only session validation, conditional live-session activity,
  generic CORS-aware 503 responses, and bearer-token precedence.
- Added a real-PostgreSQL two-repository race covering one conditional activity winner, expired-session
  rejection, and no regression from a delayed observation.

## GREEN

- Split cookie authentication into an authoritative read-only repository lookup and a separately queued,
  tenant-scoped conditional activity update.
- Moved every cookie-session lookup off the async request loop through a fixed daemon worker pool with
  bounded admission, bounded wait, fail-closed errors, and lifecycle-owned startup/shutdown.
- Preserved JWT precedence and mapped session-runtime infrastructure failures to a generic 503 without
  exposing driver details. Activity accounting stays best effort and cannot invalidate authentication.

## Verification in progress

- Runtime/session/auth focused suite: 50 passed.
- Strict-JWT, readiness, and internal-worker compatibility: 60 passed, 1 skipped.
- Real-PostgreSQL activity contract: 1 passed.
- Ruff on changed Python surfaces: passed.
- Independent QCHECK: no production finding; P3 PostgreSQL test gap remediated before formal review.

## Review (2026-08-13 22:47:18 +0700) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp-g2-session-auth`
- Branch: `fix/nonblocking-session-auth`
- Scope: working tree at base `e107253aefdfdfb811e8d32ae817dd74f735c86a`
- Commands Run: bounded diff/status inspection, RepoPrompt formal review, scoped pytest, full pytest,
  Ruff, PostgreSQL contract test, diff check

### Findings
CRITICAL
- None.

HIGH
- Remediated before disposition: saturated callers previously polled every millisecond, which could
  amplify event-loop scheduling load. Admission now rejects immediately and a one-turn plus 200-caller
  fan-in test locks the behavior.
- Remediated before disposition: partial runtime/lifespan startup failure could strand started threads.
  Startup now uses an explicit `starting` state with rollback, and the full lifespan startup sequence is
  inside the cleanup scope.

MEDIUM
- Remediated before disposition: auth tests manually started the runtime with nondeterministic weakref
  cleanup. A centralized TestClient helper and phase fixture now enter/exit real ASGI lifespan.
- Remediated before disposition: the PostgreSQL race contract only used local binaries. Required CI now
  invokes the test through `DATABASE_URL` and `EGP_CI_POSTGRES_CONTRACT`.

LOW
- None.

### Open Questions / Assumptions
- None. The activity update is intentionally best effort; authoritative authentication is never cached.

### Recommended Tests / Validation
- Rerun the complete Python suite after review remediation.
- Run frozen-lock validation, compileall, Ruff, frontend typecheck/unit/lint/build, and diff check.

### Rollout Notes
- No migration, new environment variable, public API, cookie, JWT, or worker-token contract changes.
- Session infrastructure failures fail closed as generic 503; known-invalid sessions remain 401.
- Formal disposition: PASS after all P1/P2 findings were remediated and re-review returned no findings.

## Final gates

- Post-rebase Python suite: 1882 passed, 3 skipped; skips are the established environment-conditional
  contracts, including the dedicated CI `DATABASE_URL` entrypoint.
- Frontend: API-type parity, TypeScript typecheck, ESLint, 83 unit tests, and production build passed.
- Python: full-tree Ruff and compileall passed; real local PostgreSQL activity race passed.
- Environment parity follow-up: PR #216 merged at
  `618690c05b31bccfc9e272d0f7c737fc95e18bd7`, restoring the API-type gate before PR6.
