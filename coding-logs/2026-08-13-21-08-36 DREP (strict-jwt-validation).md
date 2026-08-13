# DREP: Strict JWT Validation

Baseline: `9720179a2a59d3b32bd6799224b272b9a8960cc0`
Branch: `fix/strict-jwt-validation`

## Goal and contract

Machine bearer JWTs fail closed unless they are HS256-signed with the configured secret and carry
direct string `sub` and UUID `tenant_id` claims plus registered string `iss`, string `aud`, and
integer `exp` claims. Issuer and audience must exactly match explicit runtime configuration.
Expiration, optional `iat`, and optional `nbf` use a bounded clock-skew policy. Duplicate JOSE JSON
members, duplicate Authorization headers, malformed compact tokens, ambiguous audience arrays,
wrong algorithms, malformed claim types, and nested-metadata authority all fail uniformly with 401.

## Decisions

- The algorithm allowlist is immutable `("HS256",)`; this repository has no asymmetric/JWKS model.
- `EGP_JWT_ISSUER` and `EGP_JWT_AUDIENCE` are required whenever authentication is enabled.
- `EGP_JWT_CLOCK_SKEW_SECONDS` defaults to 30 and is bounded to 0..120.
- `role` remains optional for compatibility and must be a direct nonblank string when present; route
  guards remain authoritative for the known-role matrix and reject unknown roles with 403.
- `iat` and `nbf` remain optional registered claims and are strictly typed/validated when present.
- Browser sessions, account-action tokens, internal worker tokens, and session performance are out of
  scope.

## Files and wiring

| Surface | Change | Proof |
|---|---|---|
| `auth.py` | Immutable policy, strict JOSE preflight, PyJWT issuer/audience/expiry/algorithm/skew checks, exact claim shapes | focused strict JWT matrix |
| `config.py` | issuer/audience/skew getters and bound | config/startup tests |
| bootstrap repositories/services/middleware/main | carry policy from environment/override to verifier and reject duplicate auth headers | API tests |
| env/Compose/local scripts | declare and relay settings | operations parity tests |
| test support and bearer suites | mint compliant positive tokens; keep negative tokens explicit | affected suites |
| frontend/security/deploy docs | external signer and rollout contract | review |

## Acceptance matrix

- Valid exact issuer/audience/expiry/direct claims: accepted.
- Missing/wrong/null/blank/type-confused registered or direct claims: uniform 401.
- Expired beyond skew and future `iat`/`nbf` beyond skew: uniform 401; within-skew boundary accepted.
- HS384, `none`, malformed signature/segments/JSON, duplicate JSON members: uniform 401.
- Audience arrays and duplicate Authorization headers: uniform 401.
- Nested metadata never supplies tenant or role; invalid bearer never falls back to a valid cookie.
- Opaque browser sessions and auth-disabled operation remain compatible.

## Lifecycle gates

Focused RED/GREEN; all JWT-minting suites; env-template checks; Ruff/compileall; migration manifest;
full Python and prescribed frontend gates; independent QCHECK; formal g-check; one PR; admin merge only
after exact local evidence. External issuers must be upgraded signer-first before deployment. Rollback is
code/config-only and restores permissive token acceptance, so it is emergency-only.
