# Coding Log: Webhook SSRF Protection

Started: 2026-08-13 18:25:00 +0700
Branch: `fix/webhook-ssrf`
Baseline: `6da54410eaa7dd1c9401cc4883c8e8400de70ef1`
DREP: `coding-logs/2026-08-13-18-25-00 DREP (webhook-ssrf-protection).md`

## Planning and discovery

- PR #212 document/run RBAC was admin-squash-merged, exact-landed, and cleaned before this worktree.
- RepoPrompt and independent Terra mapped the sole tenant-controlled sink, creation boundary, both
  processor construction paths, outbox/retry semantics, and tenant-scoped audit facilities.
- The DREP rejects validate-then-reresolve designs: production transport must consume an approved
  resolved endpoint and preserve TLS SNI/certificate verification while connecting to that address.
- PRIMARY-only under g2 Q1; no DeepSeek doctor, egress, handoff, or product editing.
- The first full-suite run on merged PR #212 found one stale dashboard fixture using nonexistent
  profile UUIDs (**1791 passed, 2 skipped, 1 failed**). A separate test-only PR #213 corrected and
  exact-landed that fixture; this worktree was then rebased onto its merge SHA before continuing.

## Protected baseline

- Never stage local `.venv` or `apps/web/node_modules` setup links.
- Do not touch primary checkout dirty files or other named worktrees.

## RED and implementation

- Primary central-policy RED failed at collection because `egp_notifications.webhook_security` did
  not exist. This locked the shared policy seam before product code.
- Implemented HTTPS-only parsing, all-answer global address validation, immutable approved targets,
  bounded resolver executor/admission, pinned TLS connections, manual redirect revalidation, one
  overall deadline, and a 64 KiB diagnostic cap.
- Creation validates after tenant/entitlement checks; delivery validates every attempt. Policy blocks
  are terminal and DNS/network failures retain bounded retry semantics. Security audits contain only
  reason, stage, and attempt metadata.
- Both API/crawler shared-stack construction and the standalone webhook executor use the policy and
  audit adapter; no migration or public API schema changed.

## Gates

- Final focused webhook/policy/dispatcher/API/executor matrix: **57 passed**.
- Broader notification/webhook/signature/crawler parity matrix: **84 passed**.
- Full Python after final review remediation: **1811 passed, 2 skipped, 113 warnings**.
- Ruff lint for all apps/packages/tests and Python compileall passed.
- Migration manifest verified: **41 files**; `git diff --check` passed.
- Frontend unit: **83 passed**; typecheck, ESLint, and production build passed.

## QCHECK and formal g-check

- Independent QCHECK confirmed redirect revalidation, response/audit bounds, shared construction,
  and async executor offloading. It found one admission/reaping defect and one production-path test
  gap: resolver setup could leak a permit and timeout cleanup could return capacity before the child
  was reaped.
- Remediation moved all post-admission setup under cleanup, retained permits until a background
  reaper confirms a killed child is joined and closed, and added controlled setup-failure,
  poll-timeout, and pinned connect/handshake publication tests.
- Formal g-check iteratively caught and drove remediation for the total-deadline boundary, reserved
  address classes, raw/malformed redirects, cancellable bounded DNS, socket visibility during TCP
  connect/TLS handshake, ASCII request targets, malformed Unicode, and diagnostic-size bounds.
- Its final reason-code finding was remediated by preserving `dns_resolution_timeout` instead of
  translating the policy error to `dns_resolution_failed`; the focused suite then passed.
- **Final formal disposition: PASS — no remaining merge-blocking correctness or security defects.**
