# Coding Log — Manual PromptPay + LINE OA fix series (4 stacked PRs)

**Date:** 2026-05-30
**Base:** `origin/main` (isolated from the unmerged caddyfile commit)
**Disposition:** PRs created + g-checked, **NOT merged** (operator merges after pausing
Vercel auto-deploy). No Vercel/Lightsail deploy performed.

## Why a stack
The `/code-review` of the manual-PromptPay+LINE feature produced 10 findings.
Per the operator's request the focus is manual QR + LINE (OPN/Stripe stay in code
but disabled in the UI), shipped as a series of small, independently-green PRs.
Since nothing merges in between, the PRs are **stacked** (`gh pr create --base`).

## PRs
- **#124 `feat/manual-promptpay-base`** (base, ← main) — the manual-PromptPay +
  LINE feature, **manual-first**: create-payment-request routes through the
  server-configured provider (`GET /v1/billing/payment-config`), and the
  OPN/Stripe card method selector is hidden when the provider lacks card rails
  (`supportsCardPayment`). Fixes finding **#1**.
- **#125 `…-matching`** (← base) — **#2** rematch image-before-text slips, **#4**
  status-agnostic `find_billing_records_by_number` + uniqueness-then-payability
  in `_resolve_reference` (g-check HIGH: a paid duplicate must not collapse an
  ambiguous number), **#5** LINE deep-link prefills only oaMessage URLs (no fake
  `?text` on `/ti/p/`), **#8** INV/UPG/TRIAL reference extraction (underscores).
- **#126 `…-webhook`** (← matching) — **#3** process webhook via
  `run_in_threadpool` (event loop no longer blocked); retry-storm idempotency
  test.
- **#127 `…-settlement`** (← webhook) — **#6** atomic claim (`matched→verifying→
  verified`, migration 026) + slip-idempotent settlement (note marker preserved
  through reconcile) + atomic stale-lease recovery; **#7** admin-entered amount
  guardrail (under-payment ≠ auto-activate); **#9** shared
  `verify_hmac_sha256_base64` (LINE + OPN legacy); **#10** admin `?tab=` deep link.

## g-check (per PR, scoped Codex review before each push)
- #124: clean. #125: 1 HIGH (uniqueness-vs-payability ordering) → fixed + tested.
- #126: clean. #127: **three rounds** — claim-before-settle crash window →
  `verifying`+lease recovery; underpayment double-record → slip-idempotency
  marker; marker clobbered by reconcile + concurrent-recovery race → `note=None`
  preserve + atomic stale reclaim. Final round: resolved, no new CRITICAL/HIGH.

## Gates
ruff + 808 backend tests (all phases) green and 3× stable; web tsc + next lint +
`next build` (incl `/admin`,`/billing`) + vitest green; OPN/Stripe regression
green (validates the #9 shared-HMAC refactor).

## Operator next steps
1. Pause Vercel auto-deploy on `main` (or confirm off).
2. Merge the stack **bottom-up**: #124 → #125 → #126 → #127.
3. `git checkout main && git pull` locally after merges.
4. Deploy when ready (Vercel reâ€‘enable; Lightsail SSH pull) — not done here.
