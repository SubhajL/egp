# DREP: Webhook SSRF Protection

## 0. Profile and baseline

- Worktree: `/Users/subhajlimanond/dev/egp-g2-webhook-ssrf`
- Branch: `fix/webhook-ssrf`
- Baseline: `6da54410eaa7dd1c9401cc4883c8e8400de70ef1` (`origin/main`, after test-only
  dashboard fixture follow-up PR #213).
- Policies: root, `apps/api/AGENTS.md`, and `packages/AGENTS.md`.
- Coding Log: `coding-logs/2026-08-13-18-25-00 Coding Log (webhook-ssrf-protection).md`.
- PRIMARY by g2 Q1: network security and tenant-safe auditing. No DeepSeek.
- No migration, public schema, frontend, authentication, or entitlement change.

## 1. Goal and success

Create one outbound webhook policy used at subscription creation, immediately before every delivery,
and for every redirect. Require HTTPS, reject non-global destinations after complete A/AAAA
resolution, pin connections to approved addresses to prevent DNS rebinding, bound total time and
response bytes, and emit sanitized tenant-scoped security audit events.

Preserve outbox claims, stable event IDs and signatures, three-attempt retry semantics for transient
DNS/network failures and 429/5xx, existing terminal 4xx behavior, role/tenant/entitlement ordering,
auth-disabled tests, and both API/background executor construction paths.

## 2. Requirements

- **R1** Initial and redirect URLs require HTTPS, hostname, no credentials, no fragment/control/
  backslash/zone-id ambiguity, and a valid port.
- **R2** Validate IP literals and every resolved A/AAAA address; accept only globally routable
  unicast addresses. Mixed public/private answers fail closed, including metadata and mapped IPv4.
- **R3** Creation validates only after authorization, tenant, and entitlement gates; rejection is a
  generic 422, persists no subscription, and records a sanitized tenant audit event.
- **R4** Every delivery attempt resolves again. Terminal policy blocks never invoke transport,
  never retry, clear the claim, and record one sanitized tenant audit event.
- **R5** DNS timeout/failure is sanitized and retryable under the existing attempt policy.
- **R6** The production connector consumes an immutable approved endpoint and connects only to an
  approved address while preserving hostname TLS SNI/certificate verification and Host.
- **R7** Redirects are manual, bounded to three, preserve the signed POST for 301/302/307/308, and
  revalidate before every next hop. HTTP/private/malformed/looping redirects fail closed.
- **R8** One five-second deadline covers resolution, connect, TLS, redirects, and reads. Response
  diagnostics are streamed and capped at 64 KiB before the repository's existing 2,000-char cap.
- **R9** Environment proxies are ignored. No second hostname resolution occurs after approval.
- **R10** Audit metadata contains only stable reason/stage/attempt fields, never URL, hostname, IP,
  redirect location, response, secret, or raw resolver exception; audit failure cannot enable egress.
- **R11** Existing HTTP/private rows remain visible but are terminally blocked on their next attempt.

## 3. Files and ownership

| ID | File | Contract |
|---|---|---|
| F1 | `packages/notification-core/src/egp_notifications/webhook_security.py` | central URL/DNS/IP policy, immutable approved endpoint, safe redirecting pinned transport |
| F2 | `packages/notification-core/src/egp_notifications/webhook_delivery.py` | mandatory pre-delivery validation, typed terminal/transient handling, audit protocol |
| F3 | `apps/api/src/egp_api/services/webhook_security_audit.py` | sanitized adapter over tenant-scoped audit repository |
| F4 | `apps/api/src/egp_api/services/webhook_service.py` | creation-time validation/canonicalization and safe audit metadata |
| F5 | `apps/api/src/egp_api/routes/webhooks.py` | stable generic 422 mapping |
| F6 | `apps/api/src/egp_api/bootstrap/notifications.py` | one shared policy in the notification stack |
| F7 | `apps/api/src/egp_api/bootstrap/services.py` | shared audit/policy wiring to API creation and delivery |
| F8 | `apps/api/src/egp_api/executors/webhook_delivery.py` | standalone processor audit/policy wiring on one engine |
| F9 | `apps/api/src/egp_api/executors/crawler_agent_results.py` | shared builder signature parity |
| F10 | `tests/phase2/test_webhook_security.py` | pure policy/redirect/pinning/timeout/size RED oracle |
| F11 | `tests/phase2/test_notification_dispatch.py` | delivery rebinding, terminal block, retry/signature compatibility |
| F12 | `tests/phase4/test_webhooks_api.py` | creation rejection/no-write/audit/auth-order contracts |
| F13 | `tests/phase2/test_webhook_executor.py`, `tests/phase3/test_crawler_agent_notification_parity.py` | construction parity where required |

## 4. Test contract and wiring

Primary RED is split into deterministic, network-free tests with injected resolvers and hop senders:
URL/address rejection matrix; mixed answers; public approval; redirect revalidation; no second DNS;
shared deadline; bounded response; delivery-time rebinding; legacy HTTP terminal failure; transient DNS
retry with stable event ID; generic creation 422/no row; sanitized same-tenant audit; authorization and
tenant failures before resolution. Existing notification tests preserve payload, signature, retries,
claim clearing, and idempotency.

`build_notification_stack` is the only API/crawler composition path and exposes its single endpoint
policy. The standalone delivery executor constructs the same policy and an audit repository on its
existing shared engine. Direct repository insertion remains possible for recovery/tests, so delivery
validation is authoritative.

## 5. Slice, gates, rollout

One PRIMARY slice, no implementation delegate. Confirm RED for intended missing policy behavior,
implement F1-F9, run focused suites repeatedly, then notification/webhook/admin/crawler compatibility,
full Python and frontend gates, independent QCHECK, formal g-check, one PR, admin squash merge, exact
remote/local-main landing, and worktree removal.

Deploy API and webhook executor together. Monitor sanitized `webhook.security_*` events and failed
delivery counts. Operators replace unsafe legacy subscriptions with public HTTPS endpoints. Rollback
re-enables unsafe egress and therefore requires deactivating identified unsafe subscriptions first.

## 6. Stop lines

Stop for any allowlist of tenant-private networks, proxy-dependent transport, relaxed HTTPS policy,
schema/migration, new public response model, global DNS cache, disabling TLS verification, raw target
logging/auditing, or production file outside F1-F9. Do not broaden to fixed provider integrations.
