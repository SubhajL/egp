# Coding Log: Strict JWT Validation

Started: 2026-08-13 21:08:36 +0700
Branch: `fix/strict-jwt-validation`
Baseline: `9720179a2a59d3b32bd6799224b272b9a8960cc0`
DREP: `coding-logs/2026-08-13-21-08-36 DREP (strict-jwt-validation).md`

## Planning and ownership

- RepoPrompt planning and independent Terra reconnaissance confirmed one production JWT verifier and
  no production token issuer in this repository.
- Security implementation remains primary-owned; no DeepSeek delegation.
- Fixed HS256, required issuer/audience/expiry/direct identity, bounded skew, strict types, duplicate
  member/header rejection, uniform bearer errors, and signer-first rollout are locked.
- Browser sessions, worker tokens, account actions, and PR6 performance work are excluded.

## RED, GREEN, and integration

- Baseline probes confirmed minimal signed tokens without issuer, audience, or expiry were accepted;
  audience verification was explicitly disabled and duplicate JSON members were last-key-wins.
- Implemented immutable fixed-HS256 policy, required registered/direct claims, exact issuer and string
  audience, bounded clock skew, strict direct/temporal types, uniform 401 mapping, and canonical
  unpadded base64url/duplicate-member preflight for every compact segment.
- Wired issuer/audience/skew from explicit environment or `create_app` overrides through the
  repository bundle, app state, middleware, and verifier. Auth-enabled startup fails closed when the
  identity scope is absent; auth-disabled and cookie-session paths remain separate.
- Updated every in-repository positive test issuer and direct auth-enabled runtime test factory.
  Deployment templates, both Compose files, local scripts, frontend handoff, launch, and rotation
  docs now express the strict external-signer contract.

## Review

- Independent QCHECK found and drove correction of noncanonical padded JWT acceptance, two stale
  credential-handling docs, and missing negative tests. It also independently verified the complete
  verifier/bootstrap/fixture dataflow.
- Formal g-check found policy-construction bypasses and a signature-segment preflight gap. Both were
  remediated with invariant enforcement inside `JwtValidationPolicy` and validation of all three
  compact segments; focused tests cover malformed JSON, duplicate headers/members, `none`, tampered
  signatures, wrong algorithms, temporal boundaries, and bearer-over-cookie precedence.
- **Final formal disposition: PASS — approved for merge with no blocking findings.**

## Gates

- Focused strict-JWT suite: **46 passed**.
- Affected auth/startup/env matrix: **270 passed** before final hardening; targeted final subset:
  **53 passed, 1 skipped**.
- Full Python after all remediation: **1860 passed, 2 skipped, 114 warnings**.
- Ruff for all apps/packages/tests, Python compileall, migration manifest (**41 files**), shell syntax,
  Compose production rendering, and `git diff --check` passed.
- Frontend unit **83 passed**; typecheck, ESLint, and production build passed.
- `uv lock --check` was unavailable because `uv` is not installed on PATH; no dependency files changed.
