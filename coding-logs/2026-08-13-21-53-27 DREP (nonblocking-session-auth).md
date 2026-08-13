# DREP: Non-blocking Session Authentication

Baseline: `e107253aefdfdfb811e8d32ae817dd74f735c86a`
Branch: `fix/nonblocking-session-auth`

## Contract

- Cookie-session database validation never runs on the async request event-loop thread.
- Every request still performs an authoritative read for revocation, expiry, active tenant/user, role,
  and tenant context; no authorization cache or stale fail-open identity exists.
- Lookup concurrency and admission are bounded; saturation/database failure maps to generic 503.
- Session validation is read-only. Activity is queued best-effort without raw tokens/hashes, coalesced
  per session for five minutes, capacity-bounded, and conditionally persisted only for live sessions.
- Activity queue/write failure never changes a valid authentication result.
- Authorization header precedence, strict JWT, worker tokens, cookie format, and schema are unchanged.

## Files and proof

| Surface | Change | Proof |
|---|---|---|
| auth repository | read-only authenticated-session record; conditional touch | repository tests |
| auth service | return context plus safe session metadata | auth tests |
| session runtime | lifecycle-owned bounded daemon pool + activity queue/coalescing | deterministic async tests |
| auth selector/middleware | await cookie runtime; preserve bearer precedence; generic 503 | API tests |
| services/lifespan | single runtime owner and bounded shutdown | lifespan tests |

No migration or operator setting is introduced. Security/concurrency remains primary-owned. Full gates,
independent QCHECK, formal g-check, PR, admin merge, exact landing, and worktree removal are required.

## Acceptance detail

- Runtime state is `created` until application lifespan starts it, rejects work while stopping/stopped,
  and cannot be restarted after shutdown.
- A fixed daemon lookup pool and bounded admission queue keep event-loop latency and process shutdown
  bounded even if a database driver call never returns; timed-out work retains admission capacity until
  the underlying call finishes.
- Shutdown cancels queued lookups and joins workers only through the shared shutdown deadline.
- Real-PostgreSQL coverage uses two repository instances to prove a single conditional activity winner,
  expiry rejection, and protection against delayed timestamp regression.
